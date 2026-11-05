"""Self-hosted signaling + segment speech translation. No paid APIs."""
import asyncio, base64, os, re, secrets, subprocess, tempfile, time, threading
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from faster_whisper import WhisperModel
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import torch

ORIGINS=[x.strip() for x in os.getenv('ALLOWED_ORIGINS','http://localhost:5173').split(',')]
WHISPER=os.getenv('WHISPER_MODEL','small')
NLLB=os.getenv('NLLB_MODEL','facebook/nllb-200-distilled-600M')
MAX_AUDIO=3_000_000
rooms=defaultdict(dict)
users={}
locks=defaultdict(asyncio.Lock)
model_lock=threading.Lock()

@asynccontextmanager
async def lifespan(app):
    app.state.whisper=WhisperModel(WHISPER,device='cuda' if torch.cuda.is_available() else 'cpu',compute_type='float16' if torch.cuda.is_available() else 'int8')
    app.state.tokenizer=AutoTokenizer.from_pretrained(NLLB)
    app.state.translator=AutoModelForSeq2SeqLM.from_pretrained(NLLB).eval()
    app.state.translator.to('cpu')
    yield

app=FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=ORIGINS,allow_credentials=False,allow_methods=['GET','POST'],allow_headers=['*'])
LANGS={'ur':('ur','urd_Arab','ur'),'tr':('tr','tur_Latn','tr')}

def run_pipeline(raw,source,target):
    with tempfile.TemporaryDirectory() as tmp:
        src=Path(tmp)/'audio.webm'; wav=Path(tmp)/'audio.wav'; out=Path(tmp)/'speech.wav'
        src.write_bytes(raw)
        subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-i',str(src),'-ar','16000','-ac','1',str(wav)],check=True,timeout=30)
        segments,_=app.state.whisper.transcribe(str(wav),language=LANGS[source][0],vad_filter=True,beam_size=3)
        original=' '.join(x.text.strip() for x in segments).strip()
        if not original:return {'original':'','translated':'','audio':''}
        # Shared tokenizer is mutable; serialize inference across rooms.
        with model_lock:
            tok=app.state.tokenizer
            tok.src_lang=LANGS[source][1]
            inputs=tok(original,return_tensors='pt',truncation=True,max_length=512)
            with torch.no_grad():
                generated=app.state.translator.generate(**inputs,forced_bos_token_id=tok.convert_tokens_to_ids(LANGS[target][1]),max_new_tokens=256)
            translated=tok.batch_decode(generated,skip_special_tokens=True)[0]
        # espeak-ng is a local, offline TTS engine. Voice quality is synthetic.
        # eSpeak NG Urdu voice may not exist in a given distro build.
        # Never silently substitute a different language's voice.
        audio=''
        try:
            subprocess.run(['espeak-ng','-v',LANGS[target][2],'-s','145','-w',str(out),translated],check=True,timeout=30,capture_output=True)
            audio=base64.b64encode(out.read_bytes()).decode('ascii')
        except (subprocess.CalledProcessError,FileNotFoundError,subprocess.TimeoutExpired):
            pass
        return {'original':original,'translated':translated,'audio':audio}

@app.get('/api/health')
async def health():return {'ok':True,'model':WHISPER}

@app.websocket('/ws/{room}/{language}')
async def socket(ws:WebSocket,room:str,language:str):
    if not re.fullmatch('[a-zA-Z0-9-]{6,64}',room) or language not in LANGS:
        await ws.close(code=1008);return
    origin=ws.headers.get('origin','')
    if origin not in ORIGINS:
        await ws.close(code=1008);return
    if len(rooms)>=20 and room not in rooms:
        await ws.accept();await ws.send_json({'type':'error','message':'Server at capacity'});await ws.close();return
    if len(rooms[room])>=2 or any(p['lang']==language for p in rooms[room].values()):
        await ws.accept();await ws.send_json({'type':'error','message':'Room full or language already in use'});await ws.close();return
    await ws.accept()
    uid=secrets.token_urlsafe(18);token=secrets.token_urlsafe(32)
    previous=list(rooms[room].keys())
    rooms[room][uid]={'ws':ws,'lang':language}
    users[token]=(room,uid,time.monotonic()+7200)
    await ws.send_json({'type':'joined','id':uid,'token':token,'peers':previous})
    for pid in previous:
        try:await rooms[room][pid]['ws'].send_json({'type':'peer-joined','id':uid})
        except Exception:pass
    try:
        while True:
            msg=await ws.receive_json()
            if msg.get('type')=='signal' and isinstance(msg.get('data'),dict):
                to=msg.get('to')
                if to in rooms[room] and len(str(msg))<16000:
                    await rooms[room][to]['ws'].send_json({'type':'signal','from':uid,'data':msg['data']})
    except (WebSocketDisconnect,RuntimeError,ValueError):pass
    finally:
        rooms[room].pop(uid,None)
        users.pop(token,None)
        for peer in list(rooms[room].values()):
            try:await peer['ws'].send_json({'type':'peer-left','id':uid})
            except Exception:pass
        if not rooms[room]:rooms.pop(room,None)

@app.post('/api/process')
async def process(token:str=Form(...),audio:UploadFile=File(...)):
    entry=users.get(token)
    if not entry or entry[2]<time.monotonic():raise HTTPException(401,'Invalid or expired call token')
    room,uid,_=entry
    member=rooms.get(room,{}).get(uid)
    if not member:raise HTTPException(401,'Not in room')
    raw=await audio.read(MAX_AUDIO+1)
    if not raw or len(raw)>MAX_AUDIO:raise HTTPException(413,'Audio must be under 3 MB')
    source=member['lang'];target='tr' if source=='ur' else 'ur'
    try:
        async with locks[room]:
            result=await asyncio.to_thread(run_pipeline,raw,source,target)
    except Exception as exc:
        raise HTTPException(502,f'AI pipeline failed: {type(exc).__name__}')
    if result['original']:
        for pid,p in list(rooms.get(room,{}).items()):
            if pid!=uid:
                try:await p['ws'].send_json({'type':'translation','original':result['original'],'translated':result['translated'],'audio':result['audio']})
                except Exception:pass
    return {'original':result['original'],'translated':result['translated']}

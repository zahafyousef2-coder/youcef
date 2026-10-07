import asyncio,aiohttp,ssl,time,base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

KEY=bytes([89,103,38,116,99,37,68,69,117,104,54,37,90,99,94,56])
IV=bytes([54,111,121,90,68,114,50,50,69,51,121,99,104,106,77,37])
LOGIN_URL="https://loginbp.ppmainecoonghj.com"
CLIENT_URL="https://clientbp.ppmainecoonghj.com"
KIBOMODZ_API="https://ff.kibomodz.net/api/v1/profileboard/"
KIBOMODZ_PASSWORD="K180726733"
KIBOMODZ_BANNER="901000029"
KIBOMODZ_AVATAR="902000074"
OB_VERSION="OB55"

def vr(n):
    r=[]
    while True:
        b=n&0x7F;n>>=7
        if n:b|=0x80
        r.append(b)
        if not n:break
    return bytes(r)

def pb(fields):
    p=bytearray()
    for f,v in fields.items():
        if isinstance(v,bool):
            p.extend(vr((f<<3)|0));p.extend(vr(1 if v else 0))
        elif isinstance(v,int):
            p.extend(vr((f<<3)|0));p.extend(vr(v))
        elif isinstance(v,str):
            d=v.encode();p.extend(vr((f<<3)|2));p.extend(vr(len(d)));p.extend(d)
        elif isinstance(v,(bytes,bytearray)):
            d=bytes(v);p.extend(vr((f<<3)|2));p.extend(vr(len(d)));p.extend(d)
    return bytes(p)

def read_varint(data,pos):
    res=0;sh=0
    while pos<len(data):
        b=data[pos];pos+=1
        res|=(b&0x7F)<<sh
        if not(b&0x80):break
        sh+=7
    return res,pos

def parse_pb(data):
    fields={};pos=0;n=len(data)
    while pos<n:
        try:key,pos=read_varint(data,pos)
        except:break
        fn=key>>3;wt=key&0x07
        try:
            if wt==0:val,pos=read_varint(data,pos)
            elif wt==2:
                ln,pos=read_varint(data,pos);val=data[pos:pos+ln];pos+=ln
            elif wt==5:val=data[pos:pos+4];pos+=4
            elif wt==1:val=data[pos:pos+8];pos+=8
            else:break
        except:break
        fields.setdefault(fn,[]).append(val)
    return fields

def make_ssl():
    ctx=ssl.create_default_context()
    ctx.check_hostname=False
    ctx.verify_mode=ssl.CERT_NONE
    return ctx

def build_major(open_id,access_token):
    fields={
        3: time.strftime("%Y-%m-%d %H:%M:%S"),4: "free fire",5: 1,7: "fake garena",
        8: "Android OS 9 / API-28 (PPR1.180720.122/6736742)",9: "Handheld",
        10: "WIFI",11: "WIFI",12: 1257,13: 480,14: "240",
        15: "x86-64 | 2000 | 6",16: 7965,17: "Adreno (TM) 540",18: "OpenGL ES 3.2",
        19: "Google|e6200d04-93a3-4514-9341-d379f92c92c2",20: "14.242.36.36",
        21: "en",22: open_id,23: "4",24: "Handheld",25: "infinix x6891",
        29: access_token,30: 1,41: "WIFI",42: "WIFI",
        57: "7428b253defc164018c604a1ebbfebdf",60: 128886,61: 113471,62: 7998,
        64: 120040,65: 128886,66: 120040,67: 128886,73: 2,
        74: "/data/app/com.dts.freefireth/lib/arm64",76: 1,78: 3,79: 2,81: "64",
        83: "2019121229",86: "OpenGLES2",87: 4095,88: 4,90: "City",91: "ME",
        92: 20583,93: "android",
        94: "KqsHTxlzSl3i59tPt7bT3bNzIDdkBgGk3cO/WZnqY5h3i+mCiEozhU9+75L4xBzZExI/HsQIq8bS8vk7KzjerfDAftCvpq+MzU9ZBwlWJWqfcJOP",
        95: 111107,96: '{"cur_rate":null,"support_etc2":false}',97: 1,98: 1,
        99: "4",100: "4",104: 83371,105: 1,
        106: "https://dl.gmc.freefiremobile.com/live/ABHotUpdates/|https://core-gmc.freefiremobile.com/live/ABHotUpdates/|211c933168f55902c7dfbfd8c4e2957d",
        107: "c8e41b7a93f02d56e1a94c7b8203f5d1",
    }
    return AES.new(KEY,AES.MODE_CBC,IV).encrypt(pad(pb(fields),16))

async def oauth(uid,password):
    url="https://100067.connect.garena.com/api/v2/oauth/guest/token:grant"
    headers={"User-Agent":"GarenaMSDK/4.0.44(iPhone11,8;iOS 17.0.2;ar;MR;app 2.126.18 2019121229;)","Content-Type":"application/json; charset=utf-8"}
    body={"client_id":100067,"client_secret":"2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3","client_type":2,"device_id":"","password":password,"response_type":"token","uid":int(uid)}
    async with aiohttp.ClientSession() as s:
        async with s.post(url,headers=headers,json=body,ssl=make_ssl(),timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status!=200:return None
            j=await r.json()
            return j.get("data",j)

async def major_login(payload):
    url=f"{LOGIN_URL}/MajorLogin"
    headers={"User-Agent":"UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)","Accept":"*/*","Accept-Encoding":"deflate, gzip","X-GA-SV":str(int(time.time())),"Authorization":"Bearer","X-GA":"v1 1","ReleaseVersion":OB_VERSION,"Content-Type":"application/x-www-form-urlencoded","X-Unity-Version":"2018.4.12f1"}
    async with aiohttp.ClientSession() as s:
        async with s.post(url,data=payload,headers=headers,ssl=make_ssl(),timeout=aiohttp.ClientTimeout(total=15)) as r:
            raw=await r.read()
            return raw if r.status==200 else None

async def get_login_data(payload,token):
    url=f"{CLIENT_URL}/GetLoginData"
    headers={"Host":"clientbp.ppmainecoonghj.com","User-Agent":"UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)","Accept":"*/*","Accept-Encoding":"deflate, gzip","X-GA-SV":str(int(time.time())),"Authorization":f"Bearer {token}","X-GA":"v1 1","ReleaseVersion":OB_VERSION,"Content-Type":"application/x-www-form-urlencoded","X-Unity-Version":"2018.4.12f1"}
    async with aiohttp.ClientSession() as s:
        async with s.post(url,data=payload,headers=headers,ssl=make_ssl(),timeout=aiohttp.ClientTimeout(total=15)) as r:
            raw=await r.read()
            return raw if r.status==200 else None

def _txt(v):
    if isinstance(v,(bytes,bytearray)):
        try:return v.decode("utf-8","ignore")
        except:return ""
    return str(v) if v is not None else ""

async def fetch_profile_card(uid,name,level):
    try:
        params={
            "password":KIBOMODZ_PASSWORD,
            "name":name or f"Player_{uid}",
            "uid":str(uid),
            "level":str(int(level) if level else 2),
            "banner":KIBOMODZ_BANNER,
            "avatar":KIBOMODZ_AVATAR,
        }
        headers={
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept":"image/webp,image/png,image/*,*/*;q=0.8",
            "Referer":"https://ff.kibomodz.net/",
        }
        async with aiohttp.ClientSession() as s:
            async with s.get(KIBOMODZ_API,params=params,headers=headers,timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status!=200:return None
                raw=await r.read()
                if len(raw)<100:return None
                mime="image/png"
                if raw.startswith(b"\xff\xd8"):mime="image/jpeg"
                elif raw.startswith(b"GIF8"):mime="image/gif"
                elif raw.startswith(b"RIFF") and raw[8:12]==b"WEBP":mime="image/webp"
                return {"png":base64.b64encode(raw).decode(),"mime":mime}
    except:
        return None

async def show_bot(uid,password):
    td=await oauth(uid,password)
    if not td:return {"error":"oauth_failed"}
    open_id=td.get("open_id");access_token=td.get("access_token")
    if not open_id or not access_token:return {"error":"no_tokens"}
    ml_payload=build_major(open_id,access_token)
    ml=await major_login(ml_payload)
    if not ml:return {"error":"major_login_failed"}
    body=ml[64:]
    f=parse_pb(body)
    if 1 not in f or 8 not in f:return {"error":"parse_failed"}
    account_id=str(int(f[1][0]))
    jwt=f[8][0].decode()
    ld=await get_login_data(ml_payload,jwt)
    if not ld:return {"error":"get_login_data_failed"}
    gl=parse_pb(ld)
    uid_game=str(int(gl[1][0])) if 1 in gl else account_id
    name=_txt(gl[4][0]) if 4 in gl else ""
    region=_txt(gl[3][0]) if 3 in gl else "ME"
    level= _txt(gl[6][0]) if 6 in gl else 1
    if 2 in gl:
        try:level=int(gl[2][0])
        except:pass
    card=await fetch_profile_card(uid_game,name,level)
    return {
        "ok":True,
        "uid":uid_game,
        "name":name or f"Player_{uid_game}",
        "region":region,
        "level":2,
        "card_png":card["png"] if card else "",
        "card_mime":card["mime"] if card else "image/png",
    }

def show_bot_sync(uid,password):
    try:
        return asyncio.run(show_bot(uid,password))
    except RuntimeError:
        loop=asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(show_bot(uid,password))
        finally:
            loop.close()
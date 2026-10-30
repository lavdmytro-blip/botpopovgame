import os, json, time, hmac, hashlib, secrets, asyncio, logging, threading
from pathlib import Path
from urllib.parse import parse_qsl
from contextlib import asynccontextmanager
import httpx
import psycopg
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from psycopg.types.json import Jsonb

logging.basicConfig(level=logging.INFO)
logging.getLogger('httpx').setLevel(logging.WARNING)  # avoid logging Bot API URLs containing secrets
log = logging.getLogger('popov')
TOKEN = os.getenv('BOT_TOKEN', '').strip()
DATABASE_URL = os.getenv('DATABASE_URL', '')
PUBLIC_URL = os.getenv('PUBLIC_URL', '').strip().rstrip('/')
BOT_USERNAME = os.getenv('BOT_USERNAME', 'PopovTap_bot').strip().lstrip('@')
ADMIN_TELEGRAM_ID = os.getenv('ADMIN_TELEGRAM_ID', '').strip()
REF_INVITER_REWARD = 1500
REF_NEW_PLAYER_REWARD = 500
REF_MILESTONES = {3: 5000, 10: 20000}
LOCK = threading.RLock()
SESSIONS = {}
RECENTS = {}
RUSH_ROUNDS = {}  # active round in memory; reward counters saved in PostgreSQL
PRICE = {'tap':75,'energy':140,'regen':230,'auto':500}
SKIN_COST = {'ember':2500,'frost':8500,'royal':25000}
GEM_SKINS = {'gem_phantom': 12, 'gem_dragon': 30, 'gem_aurora': 55}
GEMS_DAILY_CAP = 12

STARS = {'neon':25,'pink':40,'obsidian':60,'solar':85,'galaxy':110,'emperor':150,'star_tap':75,'star_battery':65,'star_regen':65,'star_miner':95}
STAR_UPGRADES = {'star_tap': {'tap':3}, 'star_battery': {'energy':500}, 'star_regen': {'regen':2}, 'star_miner': {'passive':600}}
STAR_NAMES = {'neon':'Cyber Blue','pink':'Pink Nova','obsidian':'Obsidian King','solar':'Solar Storm','galaxy':'Galaxy Crown','emperor':'Tap Emperor','star_tap':'Royal Power +3','star_battery':'Infinity Cell +500','star_regen':'Turbo Charge +2','star_miner':'Gold Mine +600/час'}
BONUSES = {'ember': {'tap':1}, 'frost': {'regen':1},'royal':{'tap':2,'passive':120},'obsidian':{'tap':2},'solar':{'regen':1.5},'galaxy':{'passive':240},'emperor':{'tap':3,'regen':1},'gem_phantom':{'tap':2},'gem_dragon':{'energy':250},'gem_aurora':{'regen':1}}
QUESTS = [{"id":"10","kind":"taps","goal":10,"reward":50,"title":"10 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"25","kind":"taps","goal":25,"reward":100,"title":"25 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"50","kind":"taps","goal":50,"reward":200,"title":"50 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"100","kind":"taps","goal":100,"reward":500,"title":"100 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"200","kind":"taps","goal":200,"reward":800,"title":"200 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"350","kind":"taps","goal":350,"reward":1200,"title":"350 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"500","kind":"taps","goal":500,"reward":3000,"title":"500 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"750","kind":"taps","goal":750,"reward":3500,"title":"750 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"1000","kind":"taps","goal":1000,"reward":5000,"title":"1 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"1500","kind":"taps","goal":1500,"reward":8000,"title":"1 500 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"2000","kind":"taps","goal":2000,"reward":15000,"title":"2 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"3000","kind":"taps","goal":3000,"reward":19000,"title":"3 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"5000","kind":"taps","goal":5000,"reward":30000,"title":"5 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"7500","kind":"taps","goal":7500,"reward":45000,"title":"7 500 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"10000","kind":"taps","goal":10000,"reward":65000,"title":"10 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"15000","kind":"taps","goal":15000,"reward":85000,"title":"15 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"25000","kind":"taps","goal":25000,"reward":140000,"title":"25 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"50000","kind":"taps","goal":50000,"reward":260000,"title":"50 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"100000","kind":"taps","goal":100000,"reward":500000,"title":"100 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"tap_1","kind":"upgrade:tap","goal":1,"reward":120,"title":"Сила тапа · ур. 1","emoji":"⚡","desc":"Улучшай способности"},{"id":"tap_3","kind":"upgrade:tap","goal":3,"reward":650,"title":"Сила тапа · ур. 3","emoji":"⚡","desc":"Улучшай способности"},{"id":"tap_5","kind":"upgrade:tap","goal":5,"reward":1500,"title":"Сила тапа · ур. 5","emoji":"⚡","desc":"Улучшай способности"},{"id":"tap_10","kind":"upgrade:tap","goal":10,"reward":5000,"title":"Сила тапа · ур. 10","emoji":"⚡","desc":"Улучшай способности"},{"id":"tap_20","kind":"upgrade:tap","goal":20,"reward":15000,"title":"Сила тапа · ур. 20","emoji":"⚡","desc":"Улучшай способности"},{"id":"energy_1","kind":"upgrade:energy","goal":1,"reward":130,"title":"Запас энергии · ур. 1","emoji":"🔋","desc":"Улучшай способности"},{"id":"energy_3","kind":"upgrade:energy","goal":3,"reward":750,"title":"Запас энергии · ур. 3","emoji":"🔋","desc":"Улучшай способности"},{"id":"energy_5","kind":"upgrade:energy","goal":5,"reward":2000,"title":"Запас энергии · ур. 5","emoji":"🔋","desc":"Улучшай способности"},{"id":"energy_10","kind":"upgrade:energy","goal":10,"reward":6000,"title":"Запас энергии · ур. 10","emoji":"🔋","desc":"Улучшай способности"},{"id":"regen_1","kind":"upgrade:regen","goal":1,"reward":180,"title":"Регенерация · ур. 1","emoji":"💚","desc":"Улучшай способности"},{"id":"regen_3","kind":"upgrade:regen","goal":3,"reward":800,"title":"Регенерация · ур. 3","emoji":"💚","desc":"Улучшай способности"},{"id":"regen_5","kind":"upgrade:regen","goal":5,"reward":2200,"title":"Регенерация · ур. 5","emoji":"💚","desc":"Улучшай способности"},{"id":"regen_10","kind":"upgrade:regen","goal":10,"reward":7000,"title":"Регенерация · ур. 10","emoji":"💚","desc":"Улучшай способности"},{"id":"auto_1","kind":"upgrade:auto","goal":1,"reward":250,"title":"Автодобыча · ур. 1","emoji":"🤖","desc":"Улучшай способности"},{"id":"auto_3","kind":"upgrade:auto","goal":3,"reward":900,"title":"Автодобыча · ур. 3","emoji":"🤖","desc":"Улучшай способности"},{"id":"auto_5","kind":"upgrade:auto","goal":5,"reward":3000,"title":"Автодобыча · ур. 5","emoji":"🤖","desc":"Улучшай способности"},{"id":"auto_10","kind":"upgrade:auto","goal":10,"reward":9000,"title":"Автодобыча · ур. 10","emoji":"🤖","desc":"Улучшай способности"},{"id":"skins_2","kind":"skins","goal":2,"reward":250,"title":"Коллекционер · 2 скина","emoji":"🎭","desc":"Открывай новые облики"},{"id":"skins_3","kind":"skins","goal":3,"reward":800,"title":"Коллекционер · 3 скина","emoji":"🎭","desc":"Открывай новые облики"},{"id":"skins_4","kind":"skins","goal":4,"reward":1500,"title":"Коллекционер · 4 скина","emoji":"🎭","desc":"Открывай новые облики"},{"id":"skins_5","kind":"skins","goal":5,"reward":3200,"title":"Коллекционер · 5 скина","emoji":"🎭","desc":"Открывай новые облики"},{"id":"friends_1","kind":"refs","goal":1,"reward":2000,"title":"Команда · 1 друзей","emoji":"👥","desc":"Приглашай настоящих игроков"},{"id":"friends_3","kind":"refs","goal":3,"reward":4500,"title":"Команда · 3 друзей","emoji":"👥","desc":"Приглашай настоящих игроков"},{"id":"friends_5","kind":"refs","goal":5,"reward":9000,"title":"Команда · 5 друзей","emoji":"👥","desc":"Приглашай настоящих игроков"},{"id":"friends_10","kind":"refs","goal":10,"reward":18000,"title":"Команда · 10 друзей","emoji":"👥","desc":"Приглашай настоящих игроков"},{"id":"upgrades_1","kind":"all_upgrades","goal":1,"reward":200,"title":"Инженер · 1 улучшений","emoji":"🛠️","desc":"Прокачивай любые параметры"},{"id":"upgrades_3","kind":"all_upgrades","goal":3,"reward":600,"title":"Инженер · 3 улучшений","emoji":"🛠️","desc":"Прокачивай любые параметры"},{"id":"upgrades_5","kind":"all_upgrades","goal":5,"reward":1200,"title":"Инженер · 5 улучшений","emoji":"🛠️","desc":"Прокачивай любые параметры"},{"id":"upgrades_10","kind":"all_upgrades","goal":10,"reward":3300,"title":"Инженер · 10 улучшений","emoji":"🛠️","desc":"Прокачивай любые параметры"},{"id":"upgrades_20","kind":"all_upgrades","goal":20,"reward":8000,"title":"Инженер · 20 улучшений","emoji":"🛠️","desc":"Прокачивай любые параметры"}]
QUEST_BY_ID = {q['id']: q for q in QUESTS}

def quest_progress(player, quest):
    kind=quest['kind']
    if kind=='taps': return int(player.get('totalTaps',0))
    if kind.startswith('upgrade:'): return int(player.get('upgrades',{}).get(kind.split(':',1)[1],0))
    if kind=='all_upgrades': return sum(int(x) for x in player.get('upgrades',{}).values())
    if kind=='skins': return len(player.get('skins',[]))
    if kind=='refs': return int(player.get('ref_count',0))
    return 0

state = {'users':{},'charges':{},'maintenance':False,'clans':{}}
conn = None

def db_conn():
    global conn
    if not DATABASE_URL:
        raise RuntimeError('DATABASE_URL missing. Add PostgreSQL addon and a secret variable.')
    if conn is None or conn.closed:
        conn = psycopg.connect(DATABASE_URL, autocommit=True, connect_timeout=10)
    return conn

def initialize():
    global state
    c=db_conn()
    c.execute('CREATE TABLE IF NOT EXISTS game_state (id INTEGER PRIMARY KEY, state JSONB NOT NULL)')
    c.execute('INSERT INTO game_state (id,state) VALUES (1,%s) ON CONFLICT (id) DO NOTHING',[Jsonb(state)])
    row=c.execute('SELECT state FROM game_state WHERE id=1').fetchone()
    state=row[0] if row else state
    state.setdefault('users',{});state.setdefault('charges',{});state.setdefault('maintenance',False);state.setdefault('clans',{});state.setdefault('admin_log',[])

def persist():
    db_conn().execute('UPDATE game_state SET state=%s WHERE id=1',[Jsonb(state)])

def is_admin(uid, player=None):
    return bool(ADMIN_TELEGRAM_ID and str(uid) == ADMIN_TELEGRAM_ID)


# Clan competition: verified energy-backed taps contribute to weekly score.
def week_key():
    from datetime import datetime, timezone, timedelta
    d=datetime.now(timezone.utc).date()
    monday=d-timedelta(days=d.weekday())
    return monday.isoformat()

def clan_public(cid, caller=None):
    c=state['clans'][cid]
    w=week_key()
    entries=[]
    for member in c['members']:
        u=state['users'].get(member,{})
        prof=u.get('profile',{})
        entries.append({'name':prof.get('name') or 'Игрок','username':prof.get('username',''),
                        'photo_url':prof.get('photo_url',''), 'score':int(u.get('clan_week_points',{}).get(w,0)),
                        'isMe':member==caller, 'isOwner':member==c['owner']})
    entries.sort(key=lambda e:-e['score'])
    return {'id':cid,'name':c['name'],'code':c['code'],'owner':c['owner']==caller,
            'members':len(c['members']),'capacity':50,'score':sum(x['score'] for x in entries),
            'week':w,'players':entries}

def clan_summary(uid):
    mine=next((cid for cid,c in state['clans'].items() if uid in c['members']),None)
    ranking=sorted((clan_public(cid) for cid in state['clans']), key=lambda c:(-c['score'],c['name']))
    top=[{'rank':i+1,'id':c['id'],'name':c['name'],'members':c['members'],'score':c['score'],'isMine':c['id']==mine} for i,c in enumerate(ranking[:50])]
    return {'myClan':clan_public(mine,uid) if mine else None,'top':top,'week':week_key(),
            'myRank':next((i+1 for i,c in enumerate(ranking) if c['id']==mine),None)}

def referral_view(player):
    count = int(player.get('ref_count', 0))
    return {'count': count, 'inviter_reward': REF_INVITER_REWARD,
            'friend_reward': REF_NEW_PLAYER_REWARD,
            'milestones': [{'friends': n, 'reward': val, 'completed': count >= n}
                           for n, val in REF_MILESTONES.items()]}

def initial():
    return {'balance':0,'totalTaps':0,'energy':1000,'last':time.time()*1000,'upgrades':{'tap':0,'energy':0,'regen':0,'auto':0},'skin':'classic','skins':['classic'],'claimed':[],'star_upgrades':[],'gems':0,'turbo_day':'','turbo_until':0,'gems_daily':{},'rush_week_best':{}}

def award_gems(p, trials=1, chance_percent=2, cap=GEMS_DAILY_CAP):
    """Free, non-tradeable game drops, awarded by server on confirmed actions."""
    from datetime import datetime, timezone
    day=datetime.now(timezone.utc).date().isoformat()
    daily=p.setdefault('gems_daily', {})
    if daily.get('day')!=day: daily.clear();daily.update(day=day,earned=0)
    room=max(0,cap-int(daily.get('earned',0)))
    if not room: return 0
    won=sum(1 for _ in range(max(0,min(40,int(trials)))) if secrets.randbelow(1000)<int(chance_percent*10))
    gained=min(room,won)
    if gained:
        daily['earned']=int(daily.get('earned',0))+gained
        p['gems']=int(p.get('gems',0))+gained
    return gained

def bonus(p,k): return BONUSES.get(p.get('skin','classic'),{}).get(k,0) + sum(STAR_UPGRADES.get(id,{}).get(k,0) for id in p.get('star_upgrades',[]))
def max_energy(p): return 1000 + 300*p['upgrades']['energy'] + bonus(p,'energy')
def recharge(p): return 1+.75*p['upgrades']['regen']+bonus(p,'regen')
def passive(p): return 120*p['upgrades']['auto']+bonus(p,'passive')
def tick(p):
    now=time.time()*1000
    dt=min(86400,max(0,(now-p.get('last',now))/1000))
    p['energy']=min(max_energy(p),p['energy']+dt*recharge(p))
    p['balance']+=dt*passive(p)/3600
    p['last']=now

def telegram_user(init_data):
    if not TOKEN: raise ValueError('BOT_TOKEN not set')
    try:
        pairs=dict(parse_qsl(init_data,keep_blank_values=True))
        expected=pairs.pop('hash','')
        # Include 'signature' in bot-token HMAC validation; only 'hash' is excluded.
        auth=int(pairs.get('auth_date','0'))
        if not expected or abs(time.time()-auth)>86400: raise ValueError('Telegram authorization expired')
        check='\n'.join(f'{key}={value}' for key,value in sorted(pairs.items()))
        secret=hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
        signature=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,signature): raise ValueError('Invalid Telegram signature')
        user=json.loads(pairs.get('user','null'))
        if not isinstance(user,dict) or not user.get('id'): raise ValueError('Open inside Telegram')
        return user
    except (KeyError,TypeError,ValueError,json.JSONDecodeError) as e:
        raise ValueError(f'Telegram authentication failed: {e}')

def get_player(req):
    session=req.headers.get('x-popov-session','')
    info=SESSIONS.get(session)
    if not info or info['expires']<time.time(): raise HTTPException(401,'Open the game through Telegram')
    uid=info['id']
    player=state['users'].get(uid)
    if player is None: raise HTTPException(401,'Session expired')
    tick(player)
    return uid,player

def fail(msg,status=400): raise HTTPException(status,msg)

async def telegram(method, payload):
    async with httpx.AsyncClient(timeout=38) as client:
        response=await client.post(f'https://api.telegram.org/bot{TOKEN}/{method}',json=payload)
        data=response.json()
        if not data.get('ok'): raise ValueError(data.get('description','Telegram API error'))
        return data['result']

async def polling():
    offset=0
    while True:
        try:
            updates=await telegram('getUpdates',{'offset':offset,'timeout':25,'allowed_updates':['message','pre_checkout_query']})
            for update in updates:
                offset=update['update_id']+1
                if 'pre_checkout_query' in update:
                    q=update['pre_checkout_query']
                    try:
                        item=json.loads(q['invoice_payload'])
                        ok=(str(q['from']['id'])==item['id'] and q['currency']=='XTR' and STARS.get(item['skin'])==q['total_amount'] and item['id'] in state['users'])
                    except (ValueError,KeyError,TypeError): ok=False
                    await telegram('answerPreCheckoutQuery',{'pre_checkout_query_id':q['id'],'ok':ok,**({} if ok else {'error_message':'Invalid invoice'})})
                msg=update.get('message',{})
                raw_command = msg.get('text','').split(maxsplit=1)[0].split('@')[0].lower()
                sender = str(msg.get('from', {}).get('id', ''))
                private = msg.get('chat', {}).get('type') == 'private'
                authorized = private and bool(ADMIN_TELEGRAM_ID) and sender == ADMIN_TELEGRAM_ID
                if raw_command in ('/id', '/maintenance_on', '/maintenance_off', '/status'):
                    if raw_command == '/id':
                        answer = f'🆔 Ваш Telegram ID: {sender}' if private else 'Напиши мне /id в личных сообщениях.'
                    elif not authorized:
                        answer = '⛔ Команда доступна только администратору.'
                    else:
                        if raw_command in ('/maintenance_on', '/maintenance_off'):
                            with LOCK:
                                state['maintenance'] = raw_command == '/maintenance_on'
                                persist()
                        answer = ('🛠 Технический перерыв ВКЛЮЧЁН. Игроки увидят сообщение об обслуживании.'
                                  if state.get('maintenance') else '✅ Игра ОТКРЫТА. Игроки могут продолжать играть.')
                    await telegram('sendMessage', {'chat_id': msg['chat']['id'], 'text': answer})
                    continue
                if msg.get('text','').startswith('/start') and state.get('maintenance'):
                    await telegram('sendMessage', {'chat_id':msg['chat']['id'],
                        'text':'🛠 POPOV TAP — технический перерыв. Мы обновляем игру. Прогресс сохранён. Попробуйте зайти позже.'})
                    continue
                if msg.get('text','').startswith('/start'):
                    parts=msg.get('text','').split(maxsplit=1)
                    ref=parts[1][4:] if len(parts)>1 and parts[1].startswith('ref_') else ''
                    launch_url=PUBLIC_URL+('?ref='+ref if ref.isdigit() and len(ref)<30 else '')
                    if PUBLIC_URL:
                        welcome = (
                            '👑 <b>WELCOME TO POPOV TAP!</b>\n\n'
                            'Добро пожаловать в империю $POPOV! 🚀\n\n'
                            '🪙 Тапай и собирай POPOV POINTS\n'
                            '⚡ Прокачивай силу и энергию\n'
                            '💎 Открывай редкие скины\n'
                            '🏆 Покоряй мировой лидерборд\n'
                            '🎯 Выполняй задания и получай награды\n'
                            '👥 Приглашай друзей и получай бонусы\n\n'
                            '🔥 <b>BUILD YOUR EMPIRE. BECOME A LEGEND.</b>\n'
                            '👑 <b>ONE COIN. ONE KING.</b>\n\n'
                            'Нажми кнопку ниже, чтобы начать! 👇'
                        )
                        await telegram('sendMessage', {
                            'chat_id': msg['chat']['id'],
                            'text': welcome,
                            'parse_mode': 'HTML',
                            'reply_markup': {'inline_keyboard': [[{
                                'text': '🎮 ИГРАТЬ В POPOV TAP',
                                'web_app': {'url': launch_url}
                            }]]}
                        })
                    else:
                        await telegram('sendMessage',{'chat_id':msg['chat']['id'],'text':'👑 POPOV TAP: открой игру через кнопку меню.'})
                if msg.get('text', '').split(maxsplit=1)[0].split('@')[0] == '/adminboost':
                    sender = str(msg.get('from', {}).get('id', ''))
                    # Only the configured Telegram account can use this command.
                    # Restrict it to a private conversation with the bot.
                    if ADMIN_TELEGRAM_ID and sender == ADMIN_TELEGRAM_ID and msg.get('chat', {}).get('type') == 'private':
                        with LOCK:
                            p = state['users'].setdefault(sender, initial())
                            p['balance'] = 1000000000
                            for key in PRICE:
                                p['upgrades'][key] = 25
                            p['energy'] = 1000 + 300 * p['upgrades']['energy']
                            p['last'] = time.time() * 1000
                            p['skins'] = ['classic', 'ember', 'frost', 'royal', 'neon', 'pink']
                            p['skin'] = 'royal'
                            p['admin_test'] = True
                            p['profile'] = {
                                'username': str(msg.get('from', {}).get('username', '')),
                                'name': str(msg.get('from', {}).get('first_name', 'Admin')),
                                'photo_url': ''
                            }
                            persist()
                        await telegram('sendMessage', {'chat_id': sender, 'text': '👑 ADMIN TEST: 1 000 000 000 POPOV POINTS, все скины, улучшения 25 уровня. Админ-аккаунт участвует в рейтинге с пометкой ADMIN (тестовые начисления).'})
                    else:
                        await telegram('sendMessage', {'chat_id': msg['chat']['id'], 'text': 'Команда недоступна.'})
                    continue
                pay=msg.get('successful_payment')
                if pay:
                    try:
                        item=json.loads(pay['invoice_payload']);uid=item['id'];skin=item['skin'];charge=pay['telegram_payment_charge_id']
                        if (str(msg['from']['id'])==uid and uid in state['users'] and skin in STARS and STARS[skin]==pay['total_amount'] and pay['currency']=='XTR'):
                            with LOCK:
                                if charge not in state['charges']:
                                    state['charges'][charge]={'id':uid,'skin':skin,'at':time.time()}
                                    if skin in STAR_UPGRADES:
                                        items=state['users'][uid].setdefault('star_upgrades',[])
                                        if skin not in items: items.append(skin)
                                    elif skin not in state['users'][uid]['skins']: state['users'][uid]['skins'].append(skin)
                                    persist()
                            await telegram('sendMessage',{'chat_id':uid,'text':'✅ Покупка получена! Открой POPOV TAP → Скины / Бусты.'})
                    except Exception: log.exception('Payment handling failed')
        except asyncio.CancelledError: raise
        except Exception as e:
            log.warning('Telegram polling: %s',str(e)[:180]);await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app):
    initialize()
    log.info('Database connected; users: %d',len(state['users']))
    task=asyncio.create_task(polling()) if TOKEN else None
    yield
    if task: task.cancel()
    if conn: conn.close()

app=FastAPI(lifespan=lifespan)

@app.get('/')
async def home(): return FileResponse(Path(__file__).parent/'public'/'index.html',headers={'Cache-Control':'no-store, max-age=0'})
@app.get('/coin.png')
async def coin(): return FileResponse(Path(__file__).parent/'public'/'coin.png')
@app.get('/maintenance-status')
async def maintenance_status(): return {'maintenance':bool(state.get('maintenance',False))}

@app.get('/version')
async def version(): return {'build':'POPOV_V5_CLAN_WARS_PYTHON', 'status':'online'}

@app.get('/health')
async def health(): return {'ok':True,'database':'connected','users':len(state['users'])}

@app.exception_handler(HTTPException)
async def http_error(_,exc): return JSONResponse({'error':str(exc.detail)},status_code=exc.status_code)

@app.post('/api/{action}')
async def api(action:str,request:Request):
    try: data=await request.json()
    except Exception: fail('Invalid JSON')
    if not isinstance(data,dict): fail('Invalid data')
    if state.get('maintenance',False): fail('Технический перерыв. Попробуйте позже.',503)
    if action=='auth':
        try: user=telegram_user(str(data.get('initData','')))
        except ValueError as e: fail(str(e),401)
        uid=str(user['id'])
        with LOCK:
            newcomer=uid not in state['users']
            player=state['users'].setdefault(uid,initial())
            player.setdefault('ref_count',0)
            # Awards only at the first verified Telegram login; never on reload.
            if newcomer:
                ref=str(data.get('ref',''))
                if ref.isdigit() and ref != uid and ref in state['users']:
                    inviter = state['users'][ref]
                    player['referred_by']=ref
                    player['ref_bonus_awarded']=True
                    player['balance'] += REF_NEW_PLAYER_REWARD
                    inviter['balance'] += REF_INVITER_REWARD
                    inviter['ref_count']=int(inviter.get('ref_count',0))+1
                    for goal, reward in REF_MILESTONES.items():
                        if inviter['ref_count'] == goal:
                            inviter['balance'] += reward
            player['is_admin'] = is_admin(uid, player)
            name=' '.join(str(user.get(k,'')).strip() for k in ('first_name','last_name')).strip()[:70]
            photo=str(user.get('photo_url',''))
            player['profile']={'username':str(user.get('username',''))[:35], 'name':name or 'Игрок POPOV', 'photo_url':photo[:1000] if photo.startswith('https://') else ''}
            tick(player);persist()
            token=secrets.token_hex(32);SESSIONS[token]={'id':uid,'expires':time.time()+86400}
            return {'session':token,'player':player,'profile':user,'ref_count':player.get('ref_count',0), 'referral':referral_view(player), 'isAdmin':is_admin(uid, player)}
    with LOCK:
        uid,p=get_player(request)
        if action.startswith('admin-'):
            # Every admin request is authenticated by the server-side session + Telegram ID.
            if not is_admin(uid): fail('Недостаточно прав',403)
            if action=='admin-list':
                query=str(data.get('query','')).strip().lower()[:80]
                matches=[]
                for target_id, target in state['users'].items():
                    prof=target.get('profile',{})
                    label=str(prof.get('username','')).lower()
                    if query and query not in target_id and query not in label and query not in str(prof.get('name','')).lower(): continue
                    matches.append({'id':target_id,'name':prof.get('name','Игрок'), 'username':prof.get('username',''), 'balance':int(target.get('balance',0)), 'gems':int(target.get('gems',0)), 'excluded':bool(target.get('leaderboard_excluded',False))})
                return {'users':matches[:80],'total':len(matches),'skins':sorted(set(['classic']+list(SKIN_COST)+list(GEM_SKINS)+[k for k in STARS if k not in STAR_UPGRADES])),'upgrades':list(PRICE),'star_upgrades':list(STAR_UPGRADES),'log':state.get('admin_log',[])[-20:][::-1]}
            if action=='admin-edit':
                target_id=str(data.get('id','')).strip()
                target=state['users'].get(target_id)
                if not target: fail('Игрок не найден',404)
                change=str(data.get('operation',''))
                value=data.get('value')
                if change in ('points','gems'):
                    if type(value) is not int or abs(value)>10000000: fail('Допустимо целое число от -10000000 до 10000000')
                    field='balance' if change=='points' else 'gems'
                    target[field]=max(0,int(target.get(field,0))+value)
                elif change=='skin':
                    skin=str(value)
                    allowed=set(['classic'])|set(SKIN_COST)|set(GEM_SKINS)|{k for k in STARS if k not in STAR_UPGRADES}
                    if skin not in allowed: fail('Неизвестный скин')
                    skins=target.setdefault('skins',['classic'])
                    if skin not in skins: skins.append(skin)
                elif change=='upgrade':
                    key=str(data.get('key',''))
                    if key not in PRICE or type(value) is not int or not (0<=value<=100): fail('Уровень улучшения: 0–100')
                    target.setdefault('upgrades',{})[key]=value
                    target['energy']=min(max_energy(target),target.get('energy',0))
                elif change=='star-upgrade':
                    key=str(value)
                    if key not in STAR_UPGRADES: fail('Неизвестное усиление')
                    ups=target.setdefault('star_upgrades',[])
                    if key not in ups: ups.append(key)
                elif change=='exclude':
                    if type(value) is not bool: fail('Нужно true/false')
                    target['leaderboard_excluded']=value
                else: fail('Неизвестное действие')
                from datetime import datetime,timezone
                audit={'time':datetime.now(timezone.utc).isoformat(timespec='seconds'),'admin':uid,'target':target_id,'operation':change,'value':value,'key':data.get('key','') if change=='upgrade' else ''}
                state.setdefault('admin_log',[]).append(audit)
                state['admin_log']=state['admin_log'][-250:]
                persist()
                return {'ok':True,'user':{'id':target_id,'balance':target.get('balance',0),'gems':target.get('gems',0),'excluded':target.get('leaderboard_excluded',False)},'log':audit}
            fail('Неизвестная админ-команда',404)
        if action=='turbo-start':
            from datetime import datetime, timezone
            today=datetime.now(timezone.utc).date().isoformat()
            now=time.time()
            if p.get('turbo_day')==today: fail('Сегодня турбо уже использовано. Попробуй завтра.')
            p['turbo_day']=today
            p['turbo_until']=now+60
            persist()
            return {'player':p,'seconds':60,'multiplier':15}
        if action=='rush-start':
            from datetime import datetime, timezone
            today=datetime.now(timezone.utc).date().isoformat()
            info=p.setdefault('rush_daily',{})
            if info.get('day')!=today: info.update(day=today,claimed=0)
            if info.get('claimed',0)>=3: fail('Сегодня все 3 наградных раунда сыграны. Приходи завтра.')
            current=RUSH_ROUNDS.get(uid)
            if current and time.time()-current['start']<27: fail('Текущий раунд ещё идёт')
            round_id=secrets.token_urlsafe(18)
            RUSH_ROUNDS[uid]={'id':round_id,'start':time.time()}
            persist()
            return {'round_id':round_id,'duration':25,'remaining':3-info.get('claimed',0)}
        elif action=='rush-finish':
            from datetime import datetime, timezone
            current=RUSH_ROUNDS.get(uid)
            if not current or str(data.get('round_id',''))!=current['id']: fail('Раунд не найден или уже завершён')
            elapsed=time.time()-current['start']
            if elapsed<23 or elapsed>95: fail('Раунд завершён не вовремя')
            score=data.get('score')
            if type(score) is not int or score<0 or score>65: fail('Недопустимый результат')
            # Prevent repeat claims even if a client submits twice.
            RUSH_ROUNDS.pop(uid,None)
            today=datetime.now(timezone.utc).date().isoformat()
            info=p.setdefault('rush_daily',{})
            if info.get('day')!=today: info.update(day=today,claimed=0)
            if info.get('claimed',0)>=3: fail('Дневной лимит исчерпан')
            reward=min(250,score*5)
            p['balance']+=reward
            info['claimed']+=1
            p['rush_best']=max(int(p.get('rush_best',0)),score)
            gems_gained=award_gems(p, min(3,score//12), 15)
            wk=week_key();p.setdefault('rush_week_best',{})[wk]=max(score,int(p.setdefault('rush_week_best',{}).get(wk,0)))
            persist()
            return {'reward':reward,'remaining':3-info['claimed'],'player':p,'best':p['rush_best'],'gems_gained':gems_gained}
        elif action=='tap':
            count=data.get('count')
            if type(count)!=int or count<1 or count>40: fail('Invalid tap count')
            now=time.time();recent=RECENTS.get(uid,{'at':now,'count':0})
            if now-recent['at']>1: recent={'at':now,'count':0}
            recent['count']+=count;RECENTS[uid]=recent
            if recent['count']>20: fail('Too many taps')
            done=min(count,int(p['energy']))
            p['energy']-=done;p['totalTaps']+=done;p['balance']+=done*(1+p['upgrades']['tap']+bonus(p,'tap'))*(15 if time.time()<float(p.get('turbo_until',0)) else 1)
            gems_gained=award_gems(p,done,2)
            if any(uid in c['members'] for c in state['clans'].values()):
                weekly=p.setdefault('clan_week_points',{})
                weekly[week_key()]=int(weekly.get(week_key(),0))+done
                for old in list(weekly):
                    if old!=week_key(): del weekly[old]
        elif action=='upgrade':
            key=data.get('id')
            if key not in PRICE: fail('Unknown upgrade')
            lvl=p['upgrades'][key]
            if lvl>=100: fail('Max level')
            cost=round(PRICE[key]*(1.65**lvl))
            if p['balance']<cost: fail('Not enough points')
            p['balance']-=cost;p['upgrades'][key]+=1
        elif action=='gem-skin-buy':
            key=str(data.get('id',''))
            if key not in GEM_SKINS: fail('Неизвестный Gem-скин')
            if key in p['skins']: fail('Скин уже куплен')
            if int(p.get('gems',0))<GEM_SKINS[key]: fail('Недостаточно POPOV GEMS')
            p['gems']-=GEM_SKINS[key]
            p['skins'].append(key);p['skin']=key
        elif action=='rush-leaderboard':
            wk=week_key()
            ranked=sorted(({'name':v.get('profile',{}).get('name','Игрок POPOV'), 'username':v.get('profile',{}).get('username',''), 'score':int(v.get('rush_week_best',{}).get(wk,0))} for v in state['users'].values() if int(v.get('rush_week_best',{}).get(wk,0))>0 and not v.get('leaderboard_excluded',False)),key=lambda x:-x['score'])
            return {'week':wk,'top':ranked[:30]}
        elif action=='skin-buy':
            key=data.get('id')
            if key not in SKIN_COST: fail('Unknown skin')
            if key in p['skins']: fail('Skin already owned')
            if p['balance']<SKIN_COST[key]: fail('Not enough points')
            p['balance']-=SKIN_COST[key];p['skins'].append(key);p['skin']=key
        elif action=='equip':
            if data.get('id') not in p['skins']: fail('Skin not owned')
            p['skin']=data['id']
        elif action=='claim':
            key=str(data.get('id',''))
            quest=QUEST_BY_ID.get(key)
            if not quest or key in p['claimed'] or quest_progress(p,quest)<quest['goal']: fail('Reward unavailable')
            p['balance']+=quest['reward'];p['claimed'].append(key)
        elif action=='clan-list':
            return clan_summary(uid)
        elif action=='clan-create':
            if any(uid in c['members'] for c in state['clans'].values()): fail('Ты уже состоишь в клане')
            name=str(data.get('name','')).strip()
            if not (3<=len(name)<=24) or not all(ch.isalnum() or ch in ' _-' for ch in name): fail('Название: 3–24 буквы, цифры или пробелы')
            if any(c['name'].casefold()==name.casefold() for c in state['clans'].values()): fail('Это название уже занято')
            if len(state['clans'])>=10000: fail('Лимит кланов')
            cid=secrets.token_hex(6)
            code=secrets.token_hex(4).upper()
            state['clans'][cid]={'name':name,'owner':uid,'code':code,'members':[uid]}
            persist();return clan_summary(uid)
        elif action=='clan-join':
            if any(uid in c['members'] for c in state['clans'].values()): fail('Сначала покинь свой клан')
            code=str(data.get('code','')).strip().upper()
            target=next((c for c in state['clans'].values() if c['code']==code),None)
            if not target: fail('Клан с таким кодом не найден')
            if len(target['members'])>=50: fail('Клан заполнен')
            target['members'].append(uid)
            persist();return clan_summary(uid)
        elif action=='clan-leave':
            cid=next((k for k,c in state['clans'].items() if uid in c['members']),None)
            if not cid: fail('Ты не в клане')
            c=state['clans'][cid]
            c['members'].remove(uid)
            if not c['members']: del state['clans'][cid]
            elif c['owner']==uid: c['owner']=c['members'][0]
            persist();return clan_summary(uid)
        elif action=='leaderboard':
            ranked=sorted(({'uid':id,'score':int(max(0,x['balance'])),'username':x.get('profile',{}).get('username',''),'name':x.get('profile',{}).get('name','Игрок POPOV'),'photo_url':x.get('profile',{}).get('photo_url',''),'isAdmin':is_admin(id, x)} for id,x in state['users'].items() if not x.get('leaderboard_excluded',False)),key=lambda x:(-x['score'],x['uid']))
            my_rank=next((i+1 for i,x in enumerate(ranked) if x['uid']==uid),0)
            top=[{'rank':i+1,'score':x['score'],'username':x['username'],'name':x['name'],'photo_url':x['photo_url'],'isMe':x['uid']==uid,'isAdmin':x['isAdmin']} for i,x in enumerate(ranked[:100])]
            persist();return {'top':top,'myRank':my_rank,'myScore':int(max(0,p['balance'])),'total':len(ranked)}
        elif action=='state':
            persist()
            return {'player':p, 'referral':referral_view(p), 'isAdmin':is_admin(uid,p)}
        elif action=='invoice':
            skin=data.get('id')
            if skin not in STARS: fail('Unknown item')
            if skin in p.get('skins',[]) or skin in p.get('star_upgrades',[]): fail('Already owned')
            payload=json.dumps({'id':uid,'skin':skin,'nonce':secrets.token_hex(8)})
            try:
                url=await telegram('createInvoiceLink',{'title':'POPOV TAP — '+STAR_NAMES[skin],'description':'Постоянное игровое улучшение или скин. Фиксированная покупка, без случайных наград.','payload':payload,'currency':'XTR','prices':[{'label':'POPOV TAP item','amount':STARS[skin]}]})
            except Exception as e: fail('Telegram invoice error: '+str(e),502)
            return {'url':url}
        else: fail('Not found',404)
        persist();return {'player':p, 'gems_gained':gems_gained if action=='tap' else 0}

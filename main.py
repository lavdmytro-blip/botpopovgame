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
# Public channel username, e.g. popovtap. Bot must be channel administrator.
CHANNEL_USERNAME = os.getenv('CHANNEL_USERNAME', '').strip().lstrip('@')
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
CHEST_POINTS_PRICE = 1200  # fixed virtual-points price; rewards are deterministic and disclosed

STARS = {'neon':25,'pink':40,'obsidian':60,'solar':85,'galaxy':110,'emperor':150,'star_tap':75,'star_battery':65,'star_regen':65,'star_miner':95,'popov_pass':120,'royal_chest':99}
STAR_UPGRADES = {'star_tap': {'tap':3}, 'star_battery': {'energy':500}, 'star_regen': {'regen':2}, 'star_miner': {'passive':600}}
STAR_NAMES = {'neon':'Cyber Blue','pink':'Pink Nova','obsidian':'Obsidian King','solar':'Solar Storm','galaxy':'Galaxy Crown','emperor':'Tap Emperor','star_tap':'Royal Power +3','star_battery':'Infinity Cell +500','star_regen':'Turbo Charge +2','star_miner':'Gold Mine +600/час','popov_pass':'POPOV PASS Premium — сезон','royal_chest':'Royal Treasure — гарантированные награды'}
BONUSES = {'ember': {'tap':1}, 'frost': {'regen':1},'royal':{'tap':2,'passive':120},'obsidian':{'tap':2},'solar':{'regen':1.5},'galaxy':{'passive':240},'emperor':{'tap':3,'regen':1},'gem_phantom':{'tap':2},'gem_dragon':{'energy':250},'gem_aurora':{'regen':1}}
QUESTS = [{"id":"10","kind":"taps","goal":10,"reward":50,"title":"10 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"25","kind":"taps","goal":25,"reward":100,"title":"25 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"50","kind":"taps","goal":50,"reward":200,"title":"50 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"100","kind":"taps","goal":100,"reward":500,"title":"100 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"200","kind":"taps","goal":200,"reward":800,"title":"200 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"350","kind":"taps","goal":350,"reward":1200,"title":"350 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"500","kind":"taps","goal":500,"reward":3000,"title":"500 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"750","kind":"taps","goal":750,"reward":3500,"title":"750 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"1000","kind":"taps","goal":1000,"reward":5000,"title":"1 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"1500","kind":"taps","goal":1500,"reward":8000,"title":"1 500 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"2000","kind":"taps","goal":2000,"reward":15000,"title":"2 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"3000","kind":"taps","goal":3000,"reward":19000,"title":"3 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"5000","kind":"taps","goal":5000,"reward":30000,"title":"5 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"7500","kind":"taps","goal":7500,"reward":45000,"title":"7 500 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"10000","kind":"taps","goal":10000,"reward":65000,"title":"10 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"15000","kind":"taps","goal":15000,"reward":85000,"title":"15 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"25000","kind":"taps","goal":25000,"reward":140000,"title":"25 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"50000","kind":"taps","goal":50000,"reward":260000,"title":"50 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"100000","kind":"taps","goal":100000,"reward":500000,"title":"100 000 тапов","emoji":"👆","desc":"Тапай по монете"},{"id":"tap_1","kind":"upgrade:tap","goal":1,"reward":120,"title":"Сила тапа · ур. 1","emoji":"⚡","desc":"Улучшай способности"},{"id":"tap_3","kind":"upgrade:tap","goal":3,"reward":650,"title":"Сила тапа · ур. 3","emoji":"⚡","desc":"Улучшай способности"},{"id":"tap_5","kind":"upgrade:tap","goal":5,"reward":1500,"title":"Сила тапа · ур. 5","emoji":"⚡","desc":"Улучшай способности"},{"id":"tap_10","kind":"upgrade:tap","goal":10,"reward":5000,"title":"Сила тапа · ур. 10","emoji":"⚡","desc":"Улучшай способности"},{"id":"tap_20","kind":"upgrade:tap","goal":20,"reward":15000,"title":"Сила тапа · ур. 20","emoji":"⚡","desc":"Улучшай способности"},{"id":"energy_1","kind":"upgrade:energy","goal":1,"reward":130,"title":"Запас энергии · ур. 1","emoji":"🔋","desc":"Улучшай способности"},{"id":"energy_3","kind":"upgrade:energy","goal":3,"reward":750,"title":"Запас энергии · ур. 3","emoji":"🔋","desc":"Улучшай способности"},{"id":"energy_5","kind":"upgrade:energy","goal":5,"reward":2000,"title":"Запас энергии · ур. 5","emoji":"🔋","desc":"Улучшай способности"},{"id":"energy_10","kind":"upgrade:energy","goal":10,"reward":6000,"title":"Запас энергии · ур. 10","emoji":"🔋","desc":"Улучшай способности"},{"id":"regen_1","kind":"upgrade:regen","goal":1,"reward":180,"title":"Регенерация · ур. 1","emoji":"💚","desc":"Улучшай способности"},{"id":"regen_3","kind":"upgrade:regen","goal":3,"reward":800,"title":"Регенерация · ур. 3","emoji":"💚","desc":"Улучшай способности"},{"id":"regen_5","kind":"upgrade:regen","goal":5,"reward":2200,"title":"Регенерация · ур. 5","emoji":"💚","desc":"Улучшай способности"},{"id":"regen_10","kind":"upgrade:regen","goal":10,"reward":7000,"title":"Регенерация · ур. 10","emoji":"💚","desc":"Улучшай способности"},{"id":"auto_1","kind":"upgrade:auto","goal":1,"reward":250,"title":"Автодобыча · ур. 1","emoji":"🤖","desc":"Улучшай способности"},{"id":"auto_3","kind":"upgrade:auto","goal":3,"reward":900,"title":"Автодобыча · ур. 3","emoji":"🤖","desc":"Улучшай способности"},{"id":"auto_5","kind":"upgrade:auto","goal":5,"reward":3000,"title":"Автодобыча · ур. 5","emoji":"🤖","desc":"Улучшай способности"},{"id":"auto_10","kind":"upgrade:auto","goal":10,"reward":9000,"title":"Автодобыча · ур. 10","emoji":"🤖","desc":"Улучшай способности"},{"id":"skins_2","kind":"skins","goal":2,"reward":250,"title":"Коллекционер · 2 скина","emoji":"🎭","desc":"Открывай новые облики"},{"id":"skins_3","kind":"skins","goal":3,"reward":800,"title":"Коллекционер · 3 скина","emoji":"🎭","desc":"Открывай новые облики"},{"id":"skins_4","kind":"skins","goal":4,"reward":1500,"title":"Коллекционер · 4 скина","emoji":"🎭","desc":"Открывай новые облики"},{"id":"skins_5","kind":"skins","goal":5,"reward":3200,"title":"Коллекционер · 5 скина","emoji":"🎭","desc":"Открывай новые облики"},{"id":"friends_1","kind":"refs","goal":1,"reward":2000,"title":"Команда · 1 друзей","emoji":"👥","desc":"Приглашай настоящих игроков"},{"id":"friends_3","kind":"refs","goal":3,"reward":4500,"title":"Команда · 3 друзей","emoji":"👥","desc":"Приглашай настоящих игроков"},{"id":"friends_5","kind":"refs","goal":5,"reward":9000,"title":"Команда · 5 друзей","emoji":"👥","desc":"Приглашай настоящих игроков"},{"id":"friends_10","kind":"refs","goal":10,"reward":18000,"title":"Команда · 10 друзей","emoji":"👥","desc":"Приглашай настоящих игроков"},{"id":"upgrades_1","kind":"all_upgrades","goal":1,"reward":200,"title":"Инженер · 1 улучшений","emoji":"🛠️","desc":"Прокачивай любые параметры"},{"id":"upgrades_3","kind":"all_upgrades","goal":3,"reward":600,"title":"Инженер · 3 улучшений","emoji":"🛠️","desc":"Прокачивай любые параметры"},{"id":"upgrades_5","kind":"all_upgrades","goal":5,"reward":1200,"title":"Инженер · 5 улучшений","emoji":"🛠️","desc":"Прокачивай любые параметры"},{"id":"upgrades_10","kind":"all_upgrades","goal":10,"reward":3300,"title":"Инженер · 10 улучшений","emoji":"🛠️","desc":"Прокачивай любые параметры"},{"id":"upgrades_20","kind":"all_upgrades","goal":20,"reward":8000,"title":"Инженер · 20 улучшений","emoji":"🛠️","desc":"Прокачивай любые параметры"}]
QUEST_BY_ID = {q['id']: q for q in QUESTS}

# POPOV EVENTS: server-authoritative progression (virtual rewards only).
ACHIEVEMENTS = [('first_100','Первые шаги',100),('tap_1000','Тап-мастер',1000),('tap_10000','Король тапов',10000)]
FRAMES = {'frame_cyan':(8,'💠 Ледяная'),'frame_gold':(16,'👑 Золотая'),'frame_pink':(24,'💗 Неоновая')}
PETS = {'pet_robot':(2500,'🤖 Робот'),'pet_dragon':(6000,'🐉 Дракон'),'pet_ghost':(10000,'👻 Призрак')}
SECRETS = [('secret_250','Секрет: 250 тапов',250,2),('secret_2500','Секрет: 2500 тапов',2500,5)]

def current_day():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).date().isoformat()

def current_season():
    return current_day()[:7]

def event_view(p, uid):
    day=current_day(); season=current_season()
    tapped=int(p.get('totalTaps',0)); claimed=p.get('event_claims',{})
    season_taps=int(p.get('season_taps',{}).get(season,0))
    tier=max(0,min(30,season_taps//150))
    boss=boss_daily_settle()
    guild=clan_summary(uid)
    pass_premium=season in p.get('pass_premium_seasons',[])
    return {'day':day,'season':season,'daily_taken':p.get('daily_reward_day')==day,
        'daily_streak':int(p.get('daily_streak',0)),
        'chests':int(p.get('chest_tokens',0)), 'chest_price':CHEST_POINTS_PRICE, 'gem_chest_price':10, 'star_chest_price':STARS['royal_chest'], 'royal_chest_owned':bool(p.get('royal_chest_owned')), 'chest_rewards':[250,500,1000], 'next_chest':0,
        'opened':int(p.get('chests_opened',0)),
        'tier':tier,'tier_claims':claimed.get('season',{}).get(season,[]),
        'pass_premium':pass_premium,'pass_premium_claims':claimed.get('pass_premium',{}).get(season,[]),'pass_price_stars':STARS['popov_pass'],
        'achievements':[{'id':k,'title':title,'goal':goal,'completed':tapped>=goal,'claimed':k in claimed.get('achievements',[])} for k,title,goal in ACHIEVEMENTS],
        'secret':[{'id':k,'title':title,'goal':goal,'completed':tapped>=goal,'claimed':k in claimed.get('secret',[])} for k,title,goal,gems in SECRETS],
        'frames':[{'id':k,'name':name,'price':cost} for k,(cost,name) in FRAMES.items()],
        'owned_frames':p.get('frames',[]),'frame':p.get('frame',''),
        'pets':[{'id':k,'name':name,'price':cost} for k,(cost,name) in PETS.items()],
        'owned_pets':p.get('pets',[]),'pet':p.get('pet',''),
        'stats':{'taps':tapped,'gems':int(p.get('gems',0)),'rush_best':int(p.get('rush_best',0)),'total_play_seconds':int(p.get('total_play_seconds',0)),'days':len(p.get('active_days',[]))},
        'boss':{'id':boss['id'],'name':boss['name'],'hp':boss['hp'],'max_hp':boss['max_hp'],'my_hits':boss['contributions'].get(uid,0),'defeated':False,'upgrades':boss_upgrade_view(p)},
        'clan':guild}

def update_events_taps(p, count):
    if not count:return
    season=current_season()
    season_taps=p.setdefault('season_taps',{})
    season_taps[season]=int(season_taps.get(season,0))+count
    for old in list(season_taps):
        if old!=season:del season_taps[old]
    days=p.setdefault('active_days',[])
    today=current_day()
    if today not in days:days.append(today)
    if len(days)>365:del days[:-365]
    # Every 500 confirmed taps awards one free deterministic chest token.
    previous=int(p.get('totalTaps',0))-count
    tokens=max(0,int(p.get('totalTaps',0))//500 -previous//500)
    p['chest_tokens']=min(100,int(p.get('chest_tokens',0))+tokens)


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
    # One-time migration: turn energy alerts on by default for existing players.
    # Once completed, explicit opt-outs are respected on subsequent restarts.
    if not state.get('energy_alert_default_migrated_v1'):
        for player in state['users'].values():
            player['energy_notify'] = True
            player['energy_notify_pending'] = bool(float(player.get('energy', 0)) < max_energy(player) - 0.001)
        state['energy_alert_default_migrated_v1'] = True
        persist()

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
                        'isMe':member==caller, 'isOwner':member==c['owner'], 'prefix':u.get('prefix')})
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

def clan_details(cid, uid):
    if cid not in state['clans']: fail('Клан не найден',404)
    return clan_public(cid, uid)

def referral_view(player):
    count = int(player.get('ref_count', 0))
    return {'count': count, 'inviter_reward': REF_INVITER_REWARD,
            'friend_reward': REF_NEW_PLAYER_REWARD,
            'milestones': [{'friends': n, 'reward': val, 'completed': count >= n}
                           for n, val in REF_MILESTONES.items()]}


# POPOV CITY v1. All progress is stored in existing game_state JSONB.
CITY_BUILDINGS = {
    'palace': {'name':'POPOV PALACE', 'base':900, 'max':12},
    'mine': {'name':'POPOV MINE', 'base':450, 'max':20},
    'lab': {'name':'GEMS LAB', 'base':1100, 'max':12},
    'power': {'name':'ENERGY STATION', 'base':750, 'max':12},
    'exchange': {'name':'POPOV EXCHANGE', 'base':650, 'max':10},
    'bank': {'name':'POPOV BANK', 'base':1250, 'max':12},
}

def city_levels(p):
    levels=p.setdefault('city_levels', {'palace':1,'mine':1,'lab':0,'power':0,'exchange':0})
    for k in CITY_BUILDINGS:levels.setdefault(k,0)
    return levels

def city_cost(key, level):
    return int(round(CITY_BUILDINGS[key]['base'] * 1.72**level / 10)*10)

def city_rate(levels):
    # Bonuses remain modest; all earned points are stored server-side.
    return int(30 * int(levels.get('mine',0)) + 15 * int(levels.get('palace',0)))

def city_snapshot(p):
    levels=city_levels(p)
    now=time.time()
    last=float(p.setdefault('city_last_collect', now))
    accrued=max(0,min(8*3600,now-last))*city_rate(levels)/3600
    return {'levels':levels.copy(),'city_level':sum(levels.values()),'rate':city_rate(levels),
            'stored':int(accrued),'capacity_hours':8,
            'next_costs':{k:city_cost(k,int(levels[k])) if levels[k]<CITY_BUILDINGS[k]['max'] else None for k in CITY_BUILDINGS},
            'names':{k:v['name'] for k,v in CITY_BUILDINGS.items()}}


# POPOV CITY 2.0 + daily boss leaderboard. Existing user JSON remains intact.
CITY2_BUILDINGS = {
 'palace': ('POPOV PALACE', '👑', 0), 'mine': ('POPOV MINE','⛏️',0),
 'lab': ('GEMS LAB','💎', 2), 'power': ('ENERGY STATION','⚡',2),
 'exchange': ('POPOV EXCHANGE','📈',3), 'bank': ('POPOV BANK','🏦',3)
}
# Persistent world bosses: next encounter starts only after the current one is defeated.
# All rewards are virtual in-game POPOV POINTS and Gems, with no cash value.
BOSS_MAX_HP = 50_000
BOSS_NAMES = ('ФИОЛЕТОВЫЙ ТИТАН', 'КРИСТАЛЬНЫЙ ВЛАДЫКА', 'ТЕНЕВОЙ ИМПЕРАТОР',
              'КОРОЛЬ МОЛНИЙ', 'ПОВЕЛИТЕЛЬ БЕЗДНЫ', 'НЕОНОВЫЙ СТРАЖ')
BOSS_PRIZES = ((150_000,100),(100_000,70),(70_000,45),
               (45_000,30),(35_000,22),(30_000,18),
               (25_000,15),(20_000,12),(15_000,10),(10_000,8))

# Boss power-ups use only earned in-game POPOV POINTS, never Telegram Stars.
BOSS_UPGRADE_CAPS = {'power': 10, 'charge': 5}
BOSS_UPGRADE_BASE = {'power': 5_000, 'charge': 16_000}

def boss_upgrades(player):
    levels = player.setdefault('boss_upgrades', {})
    for key in BOSS_UPGRADE_CAPS:
        levels.setdefault(key, 0)
    return levels

def boss_upgrade_cost(key, level):
    return int(round(BOSS_UPGRADE_BASE[key] * (1.8 ** level) / 100) * 100)

def boss_upgrade_view(player):
    levels = boss_upgrades(player)
    return {
        'levels': {key:int(levels[key]) for key in BOSS_UPGRADE_CAPS},
        'caps': BOSS_UPGRADE_CAPS.copy(),
        'costs': {key:(boss_upgrade_cost(key, int(levels[key])) if int(levels[key]) < BOSS_UPGRADE_CAPS[key] else None) for key in BOSS_UPGRADE_CAPS},
        'damage_per_hit': 1 + int(levels['power']),
        'bonus_every_tenth_hit': 2 * int(levels['charge']),
        'energy_per_hit': 1,
    }

def boss_daily_settle():
    """Keep the legacy function name for compatibility; no UTC resets anymore."""
    boss=state.get('world_boss')
    if not isinstance(boss,dict) or not boss:
        boss={'id':1,'name':BOSS_NAMES[0],'hp':BOSS_MAX_HP,
              'max_hp':BOSS_MAX_HP,'contributions':{},'started_at':time.time(), 'defeats':0}
        state['world_boss']=boss
        persist()
    elif boss.get('mode')!='persistent_50k_v1':
        # Migration: preserve contribution counts and progress ratio for old bosses,
        # rather than resetting all players' hits or granting retroactive prizes.
        old_max=max(1,int(boss.get('max_hp',100_000)))
        old_hp=max(0,int(boss.get('hp',old_max)))
        mapped=max(1,min(BOSS_MAX_HP,round(old_hp/old_max*BOSS_MAX_HP)))
        boss.update(id=int(boss.get('id') or 1),name=BOSS_NAMES[(int(boss.get('id') or 1)-1)%len(BOSS_NAMES)],
                    hp=mapped,max_hp=BOSS_MAX_HP,
                    contributions={str(k):max(0,int(v)) for k,v in boss.get('contributions',{}).items()},
                    started_at=float(boss.get('started_at') or time.time()),defeats=int(boss.get('defeats',0)))
        boss.pop('day',None)
        boss['mode']='persistent_50k_v1'
        persist()
    boss.setdefault('mode','persistent_50k_v1')
    return boss

def boss_result_archive(boss):
    rows=sorted(((str(uid),max(0,int(hits))) for uid,hits in boss['contributions'].items() if int(hits)>0),
                key=lambda item:(-item[1],item[0]))
    winners=[]
    for i,(user_id,hits) in enumerate(rows[:len(BOSS_PRIZES)]):
        player=state['users'].get(user_id)
        if player is None:continue
        points,gems=BOSS_PRIZES[i]
        player['balance']=float(player.get('balance',0))+points
        player['gems']=int(player.get('gems',0))+gems
        winners.append({'rank':i+1,'id':user_id,
                        'name':str(player.get('profile',{}).get('name') or 'Игрок')[:50],
                        'username':str(player.get('profile',{}).get('username') or '')[:35],
                        'hits':hits,'points':points,'gems':gems})
    result={'id':int(boss['id']),'name':boss['name'],'started_at':boss.get('started_at'),
            'defeated_at':time.time(),'total_hits':sum(x[1] for x in rows),
            'participants':len(rows),'winners':winners}
    archive=state.setdefault('boss_history',[])
    archive.append(result)
    del archive[:-25]
    state['boss_previous']=result
    next_id=int(boss['id'])+1
    state['world_boss']={'id':next_id,'name':BOSS_NAMES[(next_id-1)%len(BOSS_NAMES)],
                         'hp':BOSS_MAX_HP,'max_hp':BOSS_MAX_HP,
                         'contributions':{},'started_at':time.time(),
                         'defeats':int(boss.get('defeats',0))+1, 'mode':'persistent_50k_v1'}
    return result

def boss_leaderboard(uid):
    boss=boss_daily_settle()
    rows=sorted(((key,int(hits)) for key,hits in boss.get('contributions',{}).items() if int(hits)>0),
                key=lambda x:(-x[1],x[0]))
    top=[]
    for rank,(user_id,hits) in enumerate(rows[:30],1):
        p=state['users'].get(user_id,{})
        prof=p.get('profile',{})
        top.append({'rank':rank,'name':str(prof.get('name') or 'Игрок')[:50],
                    'username':str(prof.get('username') or '')[:35],
                    'hits':hits,'mine':uid==user_id})
    mine=next((i for i,(user_id,_) in enumerate(rows,1) if user_id==uid),None)
    return {'id':boss['id'],'name':boss['name'],'hp':boss['hp'],'max_hp':boss['max_hp'],
            'started_at':boss.get('started_at'), 'top':top,
            'my_rank':mine, 'mine_rank':mine,
            'my_hits':int(boss.get('contributions',{}).get(uid,0)),
            'participants':len(rows),'previous':state.get('boss_previous',{}),
            'history':state.get('boss_history',[])[-5:][::-1],
            'prizes':[{'rank':i+1,'points':x[0],'gems':x[1]} for i,x in enumerate(BOSS_PRIZES)],
            'minimum_hits':1, 'reset':'on_defeat'}

def city2_data(p):
    levels=city_levels(p)
    if 'bank' not in levels: levels['bank']=0
    c2=p.setdefault('city2',{})
    road=int(c2.get('road',1)); items=c2.setdefault('decor',[])
    trip=c2.get('trip')
    now=time.time()
    trip_status=None
    if isinstance(trip,dict):
        seconds=max(0,int(float(trip.get('finish',now))-now))
        trip_status={'remaining':seconds,'ready':seconds==0,'amount':int(trip.get('amount',0))}
    day=current_day()
    if c2.get('event_day')!=day:
        c2['event_day']=day;c2['event_counts']={'delivery':0,'upgrade':0,'collect':0};c2['event_claimed']=False
    kind=['delivery','upgrade','collect'][int(day.replace('-',''))%3]
    title={'delivery':'🚚 Золотой конвой','upgrade':'🏗️ Стройка века','collect':'💎 Кристальный дождь'}[kind]
    progress=int(c2['event_counts'].get(kind,0))
    snapshot=city_snapshot(p)
    return {'city':snapshot,'road':road,'road_cost':1200*road, 'road_duration':max(25,90-10*(road-1)),
        'decor':items,'decor_costs':{'statue':4500,'fountain':7500},'trip':trip_status,
        'event':{'kind':kind,'title':title,'progress':min(1,progress),'goal':1,'claimed':bool(c2['event_claimed']),
                 'reward':{'points':1000,'gems':2}},
        'lots':[{'key':k,'name':v[0],'emoji':v[1],'level':int(levels.get(k,0)),
                 'unlocked':int(levels.get('palace',1))>=v[2],
                 'cost':city_cost(k,int(levels.get(k,0))) if k in CITY_BUILDINGS else 1600}
                for k,v in CITY2_BUILDINGS.items()]}

def city2_step(p,kind):
    c2=p.setdefault('city2',{})
    city2_data(p)
    counts=c2.setdefault('event_counts',{})
    counts[kind]=int(counts.get(kind,0))+1


# Notification system. Each player chooses their message types individually.
NOTIFY_TYPES = {
 'energy':'🔋 Энергия', 'mine':'⛏️ Шахта заполнена',
 'delivery':'🚚 Доставка готова', 'boss':'👹 Новый босс',
 'top':'🏆 Попадание в топ-10', 'clans':'⚔️ Новая клановая неделя',
 'daily':'🎁 Ежедневная награда', 'turbo':'🔥 Турбо доступно',
 'event':'💎 Событие города', 'updates':'🚀 Обновления игры',
}
# Increment this env variable (e.g. 2026-11-01-v2) when publishing an update.
RELEASE_ID = os.getenv('POPOV_RELEASE_ID', '').strip()[:80]
NOTIFY_MIN_GAP = 75  # anti-spam spacing per player; not a daily limit


def notification_options(player):
    config=player.setdefault('notification_types', {})
    for kind in NOTIFY_TYPES:
        config.setdefault(kind, bool(player.get('energy_notify',True)) if kind=='energy' else False)
    return config


def notification_snapshot(uid, player, now=None):
    """Determine eligible *real* events. No game state changes or rewards here."""
    now=time.time() if now is None else now
    day=current_day()
    result={}
    # Energy: only an already-armed recharge cycle, not a fresh login with full energy.
    last=float(player.get('last',now*1000))/1000
    capacity=max_energy(player)
    energy=min(capacity,float(player.get('energy',0))+max(0,now-last)*recharge(player))
    if player.get('energy_notify_pending') and energy >= capacity-0.001:
        result['energy']=('refill','🔋 Энергия полностью восстановлена! Возвращайся в POPOV TAP.')
    levels=player.get('city_levels',{})
    rate=city_rate(levels) if levels else 0
    last_collect=float(player.get('city_last_collect',now))
    if rate>0 and now-last_collect>=8*3600:
        result['mine']=(str(int(last_collect)),'⛏️ Шахта накопила 8 часов дохода! Забери POPOV POINTS в POPOV CITY.')
    trip=player.get('city2',{}).get('trip')
    if isinstance(trip,dict) and now>=float(trip.get('finish',now+1)):
        result['delivery']=(str(int(float(trip.get('finish',now)))),'🚚 Доставка прибыла! Забери ресурсы в POPOV CITY.')
    if state.get('world_boss',{}).get('id'):
        current=state['world_boss']
        result['boss']=(str(current['id']),'👹 Новый босс: '+str(current.get('name','POPOV TITAN'))+'! Битва открыта.')
    if any(uid in clan.get('members',[]) for clan in state.get('clans',{}).values()):
        result['clans']=(week_key(),'⚔️ Началась новая неделя CLAN WARS! Соревнуйся вместе с кланом.')
    if player.get('daily_reward_day') != day:
        result['daily']=(day,'🎁 Сегодня доступна ежедневная награда POPOV TAP!')
    if player.get('turbo_day') != day:
        result['turbo']=(day,'🔥 TURBO ×15 снова доступно! Усиление ждёт тебя.')
    if int(player.get('city_levels',{}).get('palace',0))>0:
        result['event']=(day,'💎 Новое событие POPOV CITY! Открой город, чтобы увидеть задание дня.')
    if RELEASE_ID:
        result['updates']=(RELEASE_ID,'🚀 POPOV TAP обновился! Открой игру и посмотри, что нового.')
    return result


def notification_settings_view(player):
    return {'types':dict(notification_options(player)), 'labels':NOTIFY_TYPES,
            'botStarted':bool(player.get('bot_started')),
            'minGapSeconds':NOTIFY_MIN_GAP, 'dailyLimit':None}


async def game_notification_worker():
    """Per-type event idempotency stored in PostgreSQL, with cooldown and safe retry."""
    while True:
        await asyncio.sleep(65)
        if not TOKEN or state.get('maintenance'):
            continue
        pending=[]
        now=time.time()
        with LOCK:
            # Maintain persistent boss state; never reset by day.
            boss_daily_settle()
            # Determine top-10 from actual balances; no phantom rankings.
            ranked=sorted(((uid,float(p.get('balance',0))) for uid,p in state.get('users',{}).items()
                           if not p.get('leaderboard_excluded')),key=lambda x:(-x[1],x[0]))
            top10=set(uid for uid,_ in ranked[:10])
            for uid,player in state.get('users',{}).items():
                if not player.get('bot_started'):
                    continue
                flags=notification_options(player)
                memo=player.setdefault('notification_sent',{})
                events=notification_snapshot(uid,player,now)
                # Only entry into top-10, not every rank change.
                previous_top=bool(player.get('notification_top_active',False))
                in_top=uid in top10
                if in_top and not previous_top:
                    events['top']=(f'entry-{day_key(now)}-{int(now)}','🏆 Ты вошёл в топ-10 POPOV TAP!')
                if not in_top and previous_top:
                    player['notification_top_active']=False
                if in_top and not flags.get('top'):
                    player['notification_top_active']=True
                # Legacy daily energy option synced to newer setting.
                player['energy_notify']=bool(flags.get('energy'))
                if now-float(player.get('notification_last_sent_at',0)) < NOTIFY_MIN_GAP:
                    continue
                # Seed event markers when opting in: avoid retrospective floods.
                if not player.get('notification_initialized'):
                    for kind,(key,_) in events.items():
                        if kind not in ('energy','delivery'):
                            memo[kind]=key
                    player['notification_initialized']=True
                    player['notification_top_active']=in_top
                for kind,(key,message) in events.items():
                    if not flags.get(kind) or memo.get(kind)==key:
                        continue
                    # claim event before sending; avoids double sends across worker iterations.
                    memo[kind]=key
                    player['notification_last_sent_at']=now
                    if kind=='top': player['notification_top_active']=True
                    if kind=='energy': player['energy_notify_pending']=False
                    pending.append((uid,kind,key,message))
                    break  # at most one pending message per player each scan
            persist()  # save opt-in baselines, top status and any notification claims
        for uid,kind,key,message in pending[:120]:
            try:
                await telegram('sendMessage',{'chat_id':int(uid),'text':message})
            except Exception as exc:
                error=str(exc).lower()
                log.warning('Notification %s to %s: %s',kind,uid,str(exc)[:120])
                if any(t in error for t in ('blocked','chat not found','deactivated','forbidden')):
                    with LOCK:
                        user=state['users'].get(uid)
                        if user:
                            user['bot_started']=False
                            persist()
                # For transient failures, clear the claim so the next worker can retry.
                else:
                    with LOCK:
                        user=state['users'].get(uid)
                        if user and user.get('notification_sent',{}).get(kind)==key:
                            user['notification_sent'].pop(kind,None)
                            persist()


def day_key(now):
    return time.strftime('%Y-%m-%d',time.gmtime(now))

def initial():
    return {'balance':0,'totalTaps':0,'energy':1000,'last':time.time()*1000,'upgrades':{'tap':0,'energy':0,'regen':0,'auto':0},'skin':'classic','skins':['classic'],'claimed':[],'star_upgrades':[],'gems':0,'turbo_day':'','turbo_until':0,'gems_daily':{},'rush_week_best':{},'energy_notify':True,'energy_notify_pending':False,'bot_started':False}

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

# Legacy notifier is replaced by game_notification_worker().

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
                        ok=(str(q['from']['id'])==item['id'] and q['currency']=='XTR' and STARS.get(item['skin'])==q['total_amount'] and item['id'] in state['users'] and (item['skin']!='popov_pass' or item.get('season')==current_season()))
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
                    if private and sender in state['users']:
                        with LOCK:
                            state['users'][sender]['bot_started']=True
                            persist()
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
                                    if skin=='royal_chest':
                                        pp=state['users'][uid]
                                        if not pp.get('royal_chest_owned'):
                                            pp['royal_chest_owned']=True
                                            pp['gems']=int(pp.get('gems',0))+25
                                            pp['balance']=float(pp.get('balance',0))+10000
                                            owned=pp.setdefault('skins',['classic'])
                                            if 'emperor' not in owned: owned.append('emperor')
                                    elif skin=='popov_pass':
                                        season=item.get('season')
                                        if season and isinstance(season,str) and len(season)==7:
                                            passes=state['users'][uid].setdefault('pass_premium_seasons',[])
                                            if season not in passes: passes.append(season)
                                    elif skin in STAR_UPGRADES:
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
    notify_task=asyncio.create_task(game_notification_worker()) if TOKEN else None
    yield
    if task: task.cancel()
    if notify_task: notify_task.cancel()
    if conn: conn.close()

app=FastAPI(lifespan=lifespan)

@app.get('/')
async def home(): return FileResponse(Path(__file__).parent/'public'/'index.html',headers={'Cache-Control':'no-store, max-age=0'})
@app.get('/city_art.webp')
async def city_art(): return FileResponse(Path(__file__).parent/'public'/'city_art.webp',media_type='image/webp')
@app.get('/boss_titan.webp')
async def boss_titan(): return FileResponse(Path(__file__).parent/'public'/'boss_titan.webp',media_type='image/webp')
@app.get('/boss_coin.webp')
async def boss_coin_image():
    return FileResponse(Path(__file__).parent/'public'/'boss_coin.webp',media_type='image/webp')

@app.get('/boss_hit.mp3')
async def boss_hit_audio():
    return FileResponse(Path(__file__).parent/'public'/'boss_hit.mp3',media_type='audio/mpeg')

@app.get('/coin.png')
async def coin(): return FileResponse(Path(__file__).parent/'public'/'coin.png')
@app.get('/maintenance-status')
async def maintenance_status(): return {'maintenance':bool(state.get('maintenance',False))}

@app.get('/version')
async def version(): return {'build':'POPOV_V5_CLAN_WARS_PYTHON', 'status':'online'}

@app.get('/channel-config')
async def channel_config():
    return {'configured': bool(CHANNEL_USERNAME), 'url': 'https://t.me/'+CHANNEL_USERNAME if CHANNEL_USERNAME else ''}

@app.get('/health')
async def health(): return {'ok':True,'database':'connected','users':len(state['users'])}

@app.exception_handler(HTTPException)
async def http_error(_,exc): return JSONResponse({'error':str(exc.detail)},status_code=exc.status_code)


# Daily POPOV TRADE activity leaderboard, never scored by random price outcomes.
TRADE_DAILY_REWARDS = [(50000, 50), (30000, 30), (15000, 15)]
TRADE_DAILY_LIMIT = 10

def settle_trade_day():
    today = current_day()
    info = state.setdefault('trade_daily', {'day': today, 'scores': {}, 'rounds': {}})
    if info.get('day') == today:
        return info
    scores = info.get('scores', {})
    qualified = sorted(((uid, item) for uid, item in scores.items() if int(item.get('count',0)) >= 3),
                       key=lambda it: (-int(it[1].get('xp',0)), float(it[1].get('reached_at',0)), it[0]))
    winners=[]
    for rank,(uid,item) in enumerate(qualified[:3]):
        player=state['users'].get(uid)
        if player is None: continue
        points,gems=TRADE_DAILY_REWARDS[rank]
        player['balance']=int(player.get('balance',0))+points
        player['gems']=int(player.get('gems',0))+gems
        winners.append({'id':uid,'name':str(player.get('profile',{}).get('name','Игрок'))[:50],
                        'points':points,'gems':gems,'rank':rank+1})
    state['trade_previous']={'day':info.get('day'),'winners':winners}
    state['trade_daily']={'day':today,'scores':{},'rounds':{}}
    persist()  # atomic write of old-day payouts and new-day reset
    return state['trade_daily']

def trade_board(uid):
    info=settle_trade_day()
    rows=sorted(info['scores'].items(), key=lambda it:(-it[1]['xp'],it[1]['reached_at'],it[0]))
    top=[]
    for rank,(player_id,stats) in enumerate(rows[:25],start=1):
        profile=state['users'].get(player_id,{}).get('profile',{})
        top.append({'rank':rank,'name':str(profile.get('name','Игрок'))[:50],
                    'username':str(profile.get('username',''))[:35], 'xp':int(stats['xp']),
                    'count':int(stats['count']),'mine':player_id==uid})
    my=info['scores'].get(uid,{'xp':0,'count':0})
    myrank=next((i+1 for i,(player_id,_) in enumerate(rows) if player_id==uid),None)
    return {'day':info['day'],'top':top,'my_xp':int(my['xp']),'my_count':int(my['count']),
            'my_rank':myrank,'limit':TRADE_DAILY_LIMIT,
            'rewards':[{'rank':i+1,'points':v[0],'gems':v[1]} for i,v in enumerate(TRADE_DAILY_REWARDS)],
            'previous':state.get('trade_previous',{})}

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
            notification_options(player)
            player['is_admin'] = is_admin(uid, player)
            name=' '.join(str(user.get(k,'')).strip() for k in ('first_name','last_name')).strip()[:70]
            photo=str(user.get('photo_url',''))
            player['profile']={'username':str(user.get('username',''))[:35], 'name':name or 'Игрок POPOV', 'photo_url':photo[:1000] if photo.startswith('https://') else ''}
            tick(player);persist()
            token=secrets.token_hex(32);SESSIONS[token]={'id':uid,'expires':time.time()+86400}
            return {'session':token,'player':player,'profile':user,'ref_count':player.get('ref_count',0), 'referral':referral_view(player), 'isAdmin':is_admin(uid, player)}
    with LOCK:
        uid,p=get_player(request)
        if action=='play-heartbeat':
            # Only verified, active Mini App sessions count. No client-supplied seconds.
            now=time.monotonic()
            info=SESSIONS.get(request.headers.get('x-popov-session',''))
            if not info or info.get('id')!=uid: fail('Session expired',401)
            previous=info.get('play_heartbeat_at')
            info['play_heartbeat_at']=now
            # A foreground page pings every 15s. Ignore dormant/hidden gaps.
            earned=int(max(0, min(30, now-previous))) if previous is not None and 5 <= now-previous <= 40 else 0
            if earned:
                p['total_play_seconds']=max(0,int(p.get('total_play_seconds',0)))+earned
                persist()
            return {'play_seconds':int(p.get('total_play_seconds',0)), 'earned_seconds':earned}
        if action in ('boss-board','boss/leaderboard'):
            return boss_leaderboard(uid)
        if action=='city2':
            op=str(data.get('op','view'))
            if op=='view':return {'city2':city2_data(p),'player':p}
            c2=p.setdefault('city2',{})
            levels=city_levels(p)
            if op in ('build','upgrade'):
                key=str(data.get('building',''))
                if key not in CITY2_BUILDINGS:fail('Неизвестное здание')
                required=CITY2_BUILDINGS[key][2]
                if int(levels.get('palace',1))<required:fail('Сначала улучши POPOV PALACE')
                level=int(levels.get(key,0))
                if key not in CITY_BUILDINGS or level>=CITY_BUILDINGS[key]['max']:fail('Максимальный уровень')
                if op=='build' and level>0:fail('Здание уже построено')
                if op=='upgrade' and level==0:fail('Сначала построй здание')
                cost=city_cost(key,level)
                if float(p.get('balance',0))<cost:fail('Недостаточно POPOV POINTS')
                pending=city_snapshot(p)['stored']
                if pending:p['balance']=float(p.get('balance',0))+pending
                p['city_last_collect']=time.time()
                p['balance']-=cost
                levels[key]=level+1
                city2_step(p,'upgrade')
            elif op=='road':
                level=int(c2.get('road',1))
                if level>=7:fail('Дороги улучшены максимально')
                cost=1200*level
                if float(p.get('balance',0))<cost:fail('Недостаточно POPOV POINTS')
                p['balance']-=cost;c2['road']=level+1
                city2_step(p,'upgrade')
            elif op=='dispatch':
                if isinstance(c2.get('trip'),dict):fail('Доставка уже отправлена')
                amount=city_snapshot(p)['stored']
                if amount<25:fail('Добывай ресурсы: для отправки нужно 25 POINTS')
                duration=max(25,90-10*(int(c2.get('road',1))-1))
                c2['trip']={'amount':amount,'finish':time.time()+duration}
                p['city_last_collect']=time.time() # reserve mined points: cannot collect twice
            elif op=='delivery-claim':
                trip=c2.get('trip')
                if not isinstance(trip,dict):fail('Нет активной доставки')
                if time.time()<float(trip.get('finish',0)):fail('Грузовик ещё в пути')
                amount=int(trip.get('amount',0))
                p['balance']=float(p.get('balance',0))+amount
                c2.pop('trip',None)
                city2_step(p,'delivery')
            elif op=='collect':
                amount=city_snapshot(p)['stored']
                if amount<1:fail('Шахта ещё не накопила очки')
                p['balance']=float(p.get('balance',0))+amount
                p['city_last_collect']=time.time()
                city2_step(p,'collect')
            elif op=='event-claim':
                view=city2_data(p)['event']
                if view['claimed']:fail('Награда уже получена')
                if view['progress']<1:fail('Сначала выполни городское событие')
                p['balance']=float(p.get('balance',0))+1000
                p['gems']=int(p.get('gems',0))+2
                c2['event_claimed']=True
            elif op=='decor':
                kind=str(data.get('decor',''))
                costs={'statue':4500,'fountain':7500}
                if kind not in costs:fail('Неизвестное украшение')
                items=c2.setdefault('decor',[])
                if kind in items:fail('Украшение уже куплено')
                if float(p.get('balance',0))<costs[kind]:fail('Недостаточно POPOV POINTS')
                p['balance']-=costs[kind];items.append(kind)
            else:fail('Неизвестное действие города')
            persist()
            return {'city2':city2_data(p),'player':p}
        if action in ('trade-board', 'trade-start', 'trade-finish'):
            day_info=settle_trade_day()
            if action=='trade-board':
                return trade_board(uid)
            if action=='trade-start':
                if uid in day_info['rounds'] and time.time()-day_info['rounds'][uid]['start']<70:
                    fail('Предыдущая позиция ещё активна')
                current=day_info['scores'].get(uid,{'count':0})
                if int(current['count'])>=TRADE_DAILY_LIMIT:
                    fail('Сегодня достигнут лимит зачётных сделок')
                round_id=secrets.token_urlsafe(18)
                day_info['rounds'][uid]={'id':round_id,'start':time.time()}
                persist()
                return {'round_id':round_id,'duration':60}
            round_id=str(data.get('round_id',''))
            rnd=day_info['rounds'].get(uid)
            if not rnd or not hmac.compare_digest(str(rnd['id']),round_id):
                fail('Позиция не найдена или уже завершена')
            elapsed=time.time()-float(rnd['start'])
            if elapsed<20:fail('Для зачёта удерживай позицию минимум 20 секунд')
            if elapsed>120:fail('Позиция истекла. Открой новую')
            day_info['rounds'].pop(uid,None)
            score=day_info['scores'].setdefault(uid,{'count':0,'xp':0,'reached_at':0})
            score['count']+=1
            score['xp']+=10
            score['reached_at']=time.time()
            persist()
            return {'earned_xp':10,'board':trade_board(uid)}
        if action=='city':
            op=str(data.get('op','view'))
            levels=city_levels(p)
            if op=='view':
                return {'city':city_snapshot(p),'player':p}
            if op=='collect':
                info=city_snapshot(p)
                amount=int(info['stored'])
                if amount<=0:fail('Шахта пока ничего не накопила')
                p['balance']=float(p.get('balance',0))+amount
                p['city_last_collect']=time.time()
                persist()
                return {'city':city_snapshot(p),'player':p,'earned':amount}
            if op=='upgrade':
                key=str(data.get('building',''))
                if key not in CITY_BUILDINGS:fail('Неизвестное здание')
                level=int(levels[key]);limit=CITY_BUILDINGS[key]['max']
                if level>=limit:fail('Достигнут максимальный уровень')
                if key!='palace' and key!='mine' and int(levels['palace'])<2:fail('Сначала улучши POPOV PALACE до уровня 2')
                if key=='mine' and level >= int(levels['palace'])*3:fail('Сначала улучши дворец, чтобы развивать шахту дальше')
                cost=city_cost(key,level)
                if float(p.get('balance',0))<cost:fail('Не хватает POPOV POINTS')
                # Bank the production accumulated at the previous rate before increasing rate.
                pending=city_snapshot(p)['stored']
                if pending>0:p['balance']+=pending
                p['city_last_collect']=time.time()
                p['balance']-=cost
                levels[key]=level+1
                persist()
                return {'city':city_snapshot(p),'player':p,'upgraded':key,'cost':cost,'banked':pending}
            fail('Неизвестное действие POPOV CITY')
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
                    matches.append({'id':target_id,'name':prof.get('name','Игрок'), 'username':prof.get('username',''), 'balance':int(target.get('balance',0)), 'gems':int(target.get('gems',0)), 'excluded':bool(target.get('leaderboard_excluded',False)), 'prefix':target.get('prefix')})
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
                elif change=='prefix':
                    import re
                    if not isinstance(value,dict): fail('Неверный формат префикса')
                    title=str(value.get('text','')).strip()
                    color=str(value.get('color','#FFD700')).upper()
                    neon=value.get('neon',False)
                    if not title or len(title)>20 or any(ord(ch)<32 for ch in title): fail('Префикс: от 1 до 20 символов')
                    if not re.fullmatch(r'#[0-9A-F]{6}',color): fail('Цвет должен быть в формате #RRGGBB')
                    if type(neon) is not bool: fail('Неверный параметр неона')
                    target['prefix']={'text':title,'color':color,'neon':neon}
                elif change=='prefix-remove':
                    target.pop('prefix',None)
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
        if action=='mega':
            op=str(data.get('op','view'))
            claims=p.setdefault('event_claims',{})
            day=current_day()
            if op=='daily':
                if p.get('daily_reward_day')==day: fail('Сегодня награда уже получена')
                from datetime import date
                prev=p.get('daily_reward_day')
                streak=(int(p.get('daily_streak',0))+1) if prev and (date.fromisoformat(day)-date.fromisoformat(prev)).days==1 else 1
                streak=1 if streak>7 else streak
                p['daily_streak']=streak;p['daily_reward_day']=day
                p['balance']+=streak*150
                if streak==7:p['gems']=int(p.get('gems',0))+10;p['chest_tokens']=int(p.get('chest_tokens',0))+1
            elif op=='chest-buy':
                # Fixed bundle; no chance-based paid rewards.
                if float(p.get('balance',0)) < CHEST_POINTS_PRICE: fail('Недостаточно POPOV POINTS')
                p['balance'] -= CHEST_POINTS_PRICE
                p['balance'] += 800
                p['gems'] = int(p.get('gems',0)) + 1
                reward={'kind':'bundle','label':'800 POINTS + 1 Gem','points':800,'gems':1}
            elif op=='chest-gems':
                # Fixed bundle purchased for earned Gems.
                if int(p.get('gems',0)) < 10: fail('Недостаточно Gems')
                p['gems'] -= 10
                p['balance'] += 2500
                reward={'kind':'bundle','label':'2 500 POINTS','points':2500}
            elif op=='chest':
                # The only randomized chest is obtained free through verified taps.
                if int(p.get('chest_tokens',0)) < 1: fail('Сначала заработай бесплатный сундук за 500 тапов')
                p['chest_tokens'] -= 1
                p['chests_opened'] = int(p.get('chests_opened',0)) + 1
                roll=secrets.randbelow(100)
                if roll < 40:
                    p['balance'] += 500;reward={'kind':'points','amount':500,'label':'500 POINTS'}
                elif roll < 70:
                    p['balance'] += 1500;reward={'kind':'points','amount':1500,'label':'1 500 POINTS'}
                elif roll < 90:
                    p['gems'] = int(p.get('gems',0))+3;reward={'kind':'gems','amount':3,'label':'3 GEMS'}
                else:
                    # Duplicate proof: equivalent guaranteed points when the skin is already owned.
                    skins=p.setdefault('skins',['classic'])
                    if 'ember' not in skins:
                        skins.append('ember');reward={'kind':'skin','id':'ember','label':'Скин INFERNO'}
                    else:
                        p['balance'] += 2500;reward={'kind':'points','amount':2500,'label':'2 500 POINTS (повтор скина)'}
            elif op=='season':
                tier=data.get('tier')
                if type(tier) is not int or not (1<=tier<=30): fail('Неверный уровень сезона')
                if int(p.get('season_taps',{}).get(current_season(),0))<tier*150: fail('Недостаточно сезонного опыта')
                season=current_season()
                taken=claims.setdefault('season',{}).setdefault(season,[])
                if tier in taken: fail('Награда уже получена')
                taken.append(tier)
                p['balance']+=tier*100
                if tier in (10,20,30):p['gems']=int(p.get('gems',0))+5
            elif op=='pass-premium-claim':
                tier=data.get('tier')
                season=current_season()
                if type(tier) is not int or not (1<=tier<=30):fail('Неверный уровень POPOV PASS')
                if season not in p.get('pass_premium_seasons',[]):fail('Premium PASS не приобретён')
                if int(p.get('season_taps',{}).get(season,0)) < tier*150:fail('Уровень пока не открыт')
                taken=claims.setdefault('pass_premium',{}).setdefault(season,[])
                if tier in taken:fail('Награда уже получена')
                taken.append(tier)
                # Fixed and disclosed rewards; no random paid mechanics.
                p['balance']+=tier*175
                if tier%5==0:p['gems']=int(p.get('gems',0))+3
            elif op=='achievement':
                key=str(data.get('id',''))
                entry=next((x for x in ACHIEVEMENTS if x[0]==key),None)
                if not entry or int(p.get('totalTaps',0))<entry[2]:fail('Достижение ещё не выполнено')
                done=claims.setdefault('achievements',[])
                if key in done:fail('Награда уже получена')
                done.append(key);p['balance']+=entry[2]//2
            elif op=='secret':
                key=str(data.get('id',''))
                entry=next((x for x in SECRETS if x[0]==key),None)
                if not entry or int(p.get('totalTaps',0))<entry[2]:fail('Секретное задание ещё не выполнено')
                done=claims.setdefault('secret',[])
                if key in done:fail('Награда уже получена')
                done.append(key);p['gems']=int(p.get('gems',0))+entry[3]
            elif op=='frame-buy':
                key=str(data.get('id',''))
                if key not in FRAMES:fail('Неизвестная рамка')
                owned=p.setdefault('frames',[])
                if key not in owned:
                    cost=FRAMES[key][0]
                    if int(p.get('gems',0))<cost:fail('Не хватает Gems')
                    p['gems']-=cost;owned.append(key)
                p['frame']=key
            elif op=='frame-none':p['frame']=''
            elif op=='pet-buy':
                key=str(data.get('id',''))
                if key not in PETS:fail('Неизвестный питомец')
                owned=p.setdefault('pets',[])
                if key not in owned:
                    cost=PETS[key][0]
                    if int(p.get('balance',0))<cost:fail('Не хватает POPOV POINTS')
                    p['balance']-=cost;owned.append(key)
                p['pet']=key
            elif op=='pet-none':p['pet']=''
            elif op=='boss-upgrade':
                key = str(data.get('key',''))
                if key not in BOSS_UPGRADE_CAPS: fail('Неизвестное улучшение босса')
                levels = boss_upgrades(p)
                level = int(levels[key])
                if level >= BOSS_UPGRADE_CAPS[key]: fail('Максимальный уровень улучшения')
                cost = boss_upgrade_cost(key,level)
                if float(p.get('balance',0)) < cost: fail('Не хватает POPOV POINTS')
                p['balance'] -= cost
                levels[key] = level + 1
            elif op=='boss-hit':
                hits=data.get('hits',1)
                if type(hits) is not int or not (1<=hits<=15): fail('От 1 до 15 ударов')
                boss=boss_daily_settle()
                tick(p)
                upgrades=boss_upgrade_view(p)
                damage_per_hit=upgrades['damage_per_hit']
                bonus=upgrades['bonus_every_tenth_hit']
                contrib=boss.setdefault('contributions',{})
                previous=int(contrib.get(uid,0))
                damage=0
                actual=0
                # Rank is based on verified taps, not boosted damage.
                # Stop the batch when HP runs out, never spill hits into the next boss.
                for i in range(hits):
                    if int(boss['hp'])-damage <= 0: break
                    if float(p.get('energy',0)) < actual+1: break
                    ordinal=previous+actual+1
                    hit_damage=damage_per_hit + (bonus if ordinal%10==0 else 0)
                    damage += min(hit_damage, max(0,int(boss['hp'])-damage))
                    actual += 1
                if actual<1: fail('Не хватает энергии или босс уже побеждён')
                p['energy'] -= actual
                boss['hp'] = max(0,int(boss['hp'])-damage)
                contrib[uid]=previous+actual
                p['boss_total_hits']=int(p.get('boss_total_hits',0))+actual
                p['boss_total_damage']=int(p.get('boss_total_damage',0))+damage
                # Points remain per verified tap, unaffected by damage multipliers.
                p['balance']+=actual*2
                if boss['hp']==0:
                    boss_result_archive(boss)
            elif op!='view':fail('Неизвестное действие',404)
            persist()
            return {'player':p,'events':event_view(p,uid), 'chest_reward':reward if op in ('chest','chest-buy','chest-gems') else None, 'boss_hit_result':{'hits':actual,'damage':damage} if op=='boss-hit' else None}
        elif action=='rush-start':
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
            p['energy']-=done
            if done and p.get('energy_notify') and p['energy'] < max_energy(p)-0.001: p['energy_notify_pending']=True
            p['totalTaps']+=done;p['balance']+=done*(1+p['upgrades']['tap']+bonus(p,'tap'))*(15 if time.time()<float(p.get('turbo_until',0)) else 1)
            update_events_taps(p,done)
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
        elif action=='channel-claim':
            if p.get('channel_gems_claimed', False): fail('Награда за подписку уже получена')
            if not CHANNEL_USERNAME: fail('Администратор ещё не настроил канал',503)
            if not TOKEN: fail('Telegram-бот не настроен',503)
            try:
                member=await telegram('getChatMember', {'chat_id':'@'+CHANNEL_USERNAME, 'user_id':int(uid)})
            except Exception as exc:
                log.warning('Channel verification unavailable: %s',str(exc)[:160])
                fail('Не удалось проверить подписку. Убедись, что бот администратор канала.',502)
            valid = member.get('status') in ('creator','administrator','member') or (member.get('status')=='restricted' and member.get('is_member') is True)
            if not valid: fail('Подписка не найдена. Подпишись на канал и попробуй снова.')
            # Mark and persist together; prevents repeat awards after reload.
            p['gems']=int(p.get('gems',0))+50
            p['channel_gems_claimed']=True
            persist()
            return {'player':p, 'reward':50}
        elif action=='gem-skin-buy':
            key=str(data.get('id',''))
            if key not in GEM_SKINS: fail('Неизвестный Gem-скин')
            if key in p['skins']: fail('Скин уже куплен')
            if int(p.get('gems',0))<GEM_SKINS[key]: fail('Недостаточно POPOV GEMS')
            p['gems']-=GEM_SKINS[key]
            p['skins'].append(key);p['skin']=key
        elif action=='rush-leaderboard':
            wk=week_key()
            ranked=sorted(({'name':v.get('profile',{}).get('name','Игрок POPOV'), 'username':v.get('profile',{}).get('username',''), 'prefix':v.get('prefix'), 'score':int(v.get('rush_week_best',{}).get(wk,0))} for v in state['users'].values() if int(v.get('rush_week_best',{}).get(wk,0))>0 and not v.get('leaderboard_excluded',False)),key=lambda x:-x['score'])
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
        elif action=='clan-details':
            cid=str(data.get('id',''))
            return clan_details(cid,uid)
        elif action=='notification-options':
            kind=str(data.get('kind',''))
            if kind not in NOTIFY_TYPES: fail('Неизвестный тип уведомления')
            enabled=data.get('enabled')
            if type(enabled) is not bool: fail('Нужен true или false')
            opts=notification_options(p)
            events=notification_snapshot(uid,p)
            # Turning on starts listening to the NEXT occurrence of each event.
            if enabled and not opts.get(kind,False):
                if kind in events:
                    p.setdefault('notification_sent',{})[kind]=events[kind][0]
                if kind=='top':p['notification_top_active']=True
            opts[kind]=enabled
            if kind=='energy':
                p['energy_notify']=enabled
                p['energy_notify_pending']=bool(enabled and p.get('energy',0)<max_energy(p)-0.001)
            p['notification_initialized']=True
            persist()
            return {'settings':notification_settings_view(p),'player':p}
        elif action=='notification-options-get':
            return {'settings':notification_settings_view(p)}
        elif action=='notification-settings':
            enabled=data.get('enabled')
            if type(enabled) is not bool: fail('Неверное значение')
            p['energy_notify']=enabled
            notification_options(p)['energy']=enabled
            p['notification_initialized']=True
            p['energy_notify_pending']=bool(enabled and p.get('energy',0)<max_energy(p)-0.001)
            persist()
            return {'enabled':enabled,'botStarted':bool(p.get('bot_started')),'player':p}
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
            ranked=sorted(({'uid':id,'score':int(max(0,x['balance'])),'username':x.get('profile',{}).get('username',''),'name':x.get('profile',{}).get('name','Игрок POPOV'),'photo_url':x.get('profile',{}).get('photo_url',''),'isAdmin':is_admin(id, x),'prefix':x.get('prefix'),'play_seconds':max(0,int(x.get('total_play_seconds',0)))} for id,x in state['users'].items() if not x.get('leaderboard_excluded',False)),key=lambda x:(-x['score'],x['uid']))
            my_rank=next((i+1 for i,x in enumerate(ranked) if x['uid']==uid),0)
            top=[{'rank':i+1,'score':x['score'],'username':x['username'],'name':x['name'],'photo_url':x['photo_url'],'isMe':x['uid']==uid,'isAdmin':x['isAdmin'],'prefix':x.get('prefix'),'play_seconds':x['play_seconds']} for i,x in enumerate(ranked[:100])]
            persist();return {'top':top,'myRank':my_rank,'myScore':int(max(0,p['balance'])),'total':len(ranked)}
        elif action=='state':
            persist()
            return {'player':p, 'referral':referral_view(p), 'isAdmin':is_admin(uid,p)}
        elif action=='invoice':
            skin=data.get('id')
            if skin not in STARS: fail('Unknown item')
            if skin=='royal_chest':
                if p.get('royal_chest_owned'):fail('Королевский сундук уже куплен')
            elif skin=='popov_pass':
                if current_season() in p.get('pass_premium_seasons',[]):fail('Premium PASS этого сезона уже куплен')
            elif skin in p.get('skins',[]) or skin in p.get('star_upgrades',[]): fail('Already owned')
            payload=json.dumps({'id':uid,'skin':skin,'nonce':secrets.token_hex(8),**({'season':current_season()} if skin=='popov_pass' else {})})
            try:
                url=await telegram('createInvoiceLink',{'title':'POPOV TAP — '+STAR_NAMES[skin],'description':('Премиальные фиксированные награды сезона '+current_season()+'. Не продлевается автоматически.' if skin=='popov_pass' else ('Гарантированно: 10 000 POINTS, 25 Gems и скин Emperor. Только 1 раз. Без случайных призов.' if skin=='royal_chest' else 'Постоянное игровое улучшение или скин. Фиксированная покупка, без случайных наград.')),'payload':payload,'currency':'XTR','prices':[{'label':'POPOV TAP item','amount':STARS[skin]}]})
            except Exception as e: fail('Telegram invoice error: '+str(e),502)
            return {'url':url}
        else: fail('Not found',404)
        persist();return {'player':p, 'gems_gained':gems_gained if action=='tap' else 0}

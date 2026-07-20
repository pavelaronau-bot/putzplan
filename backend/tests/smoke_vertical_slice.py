"""Smoke-проверка вертикального среза Sprint 1 на живом API.

Повторяема: перед прогоном удаляет следы предыдущего запуска.
Журнал не чистится — он append-only по замыслу.
"""
import json
import os
import subprocess
import urllib
import urllib.error
import urllib.request
import uuid

B = os.environ.get('API_BASE', 'http://127.0.0.1:8000')

# Учётную запись с историей в журнале удалить нельзя: внешний ключ
# audit_logs.user_id объявлен ON DELETE RESTRICT. Это осознанное решение,
# поэтому прогон использует уникальные имена, а не чистку данных.
SUFFIX = uuid.uuid4().hex[:10]
RESET = '''
UPDATE users SET status='active', status_reason=NULL, failed_attempts=0, locked_until=NULL
 WHERE company_id='aaaa0000-0000-0000-0000-000000000001'
   AND email::text IN ('owner@demo.putzplan.de','admin@demo.putzplan.de','disp@demo.putzplan.de');
'''
subprocess.run(['psql', '-q', '-h', os.environ.get('DB_HOST', '127.0.0.1'),
                '-U', 'putzplan_migration', '-d', os.environ.get('DB_NAME', 'putzplan_dev'),
                '-c', RESET],
               env={**os.environ, 'PGPASSWORD': os.environ.get('DB_MIGRATION_PASSWORD', 'test_migration')},
               check=False, capture_output=True)
def call(m, p, body=None, token=None, cookies=None, csrf=None, origin=None):
    req = urllib.request.Request(B + p, method=m)
    req.add_header('content-type', 'application/json')
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    if cookies:
        req.add_header('Cookie', cookies)
    # Cookie-поток защищён CSRF: браузер шлёт Origin, клиент — токен двойной отправки
    if csrf:
        req.add_header('x-csrf-token', csrf)
    if origin:
        req.add_header('origin', origin)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode() or '{}'), resp.headers
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or '{}'), e.headers
        except Exception:
            return e.code, {}, e.headers


res=[]
def chk(n,c,d=''):
    res.append((n,c)); print(('  PASS  ' if c else '  FAIL  ')+n+('' if c else f'  → {d}'))

s,b,_=call('GET','/health');   chk('health 200', s==200 and b['status']=='ok',(s,b))
s,b,_=call('GET','/ready');    chk('ready: база доступна', s==200 and b['checks']['db_runtime']=='ok',(s,b))
chk('ready: партиции известны', b['checks'].get('partitions_days_left',0)>500, b['checks'])
s,b,_=call('GET','/api/v1/users'); chk('без токена 401', s==401 and b['code']=='unauthenticated',(s,b))
s,b,h=call('POST','/api/v1/auth/login',{'email':'owner@demo.putzplan.de','password':'Owner12345678'})
chk('вход владельцем 200', s==200 and 'access_token' in b,(s,b))
owner=b.get('access_token')
cookie_pairs=[c.split(';')[0] for c in (h.get_all('set-cookie') or [])] if h else []
ck='; '.join(cookie_pairs)
csrf_value=next((c.split('=',1)[1] for c in cookie_pairs if c.startswith('putzplan_csrf=')), None)
chk('refresh в HttpOnly-cookie', 'HttpOnly' in (h.get('set-cookie') or ''), h.get('set-cookie'))
s,b,_=call('POST','/api/v1/auth/login',{'email':'owner@demo.putzplan.de','password':'wrong-password'})
chk('неверный пароль 401', s==401 and b['code']=='invalid_credentials',(s,b))
s2,b2,_=call('POST','/api/v1/auth/login',{'email':'nobody@demo.putzplan.de','password':'wrong-password'})
chk('нет user enumeration', s2==401 and b2['code']==b['code'],(s2,b2))
s,b,_=call('GET','/api/v1/me',token=owner)
chk('me: права загружены', s==200 and len(b['permissions'])>50,(s,len(b.get('permissions',[]))))
chk('me: имя пользователя', b.get('full_name')=='Stefan Brandt', b.get('full_name'))
s,b,_=call('GET','/api/v1/users?limit=10',token=owner)
chk('список пользователей', s==200 and b['total']>=3,(s,b.get('total')))
s,b,_=call('POST','/api/v1/users',{'email':f'neu-{SUFFIX}@demo.putzplan.de','full_name':'Neue Person','role':'dispatcher','password':'Neuepass12345'},token=owner)
chk('создание пользователя 201', s==201 and b['status']=='active',(s,b)); new_id=b.get('id')
s,b,_=call('POST','/api/v1/users',{'email':f'neu-{SUFFIX}@demo.putzplan.de','full_name':'Dubl','role':'dispatcher'},token=owner)
chk('дубль e-mail 409', s==409,(s,b))
s,b,_=call('PATCH',f'/api/v1/users/{new_id}',{'position':'Objektleiter'},token=owner)
chk('редактирование 200', s==200 and b['position']=='Objektleiter',(s,b))
s,b,_=call('POST','/api/v1/auth/login',{'email':'disp@demo.putzplan.de','password':'Disp12345678'})
disp=b.get('access_token'); chk('вход диспетчером', s==200 and disp, s)
s,b,_=call('GET','/api/v1/users',token=disp); chk('диспетчер: users 403', s==403 and b['code']=='forbidden',(s,b))
s,b,_=call('GET','/api/v1/audit-logs',token=disp); chk('диспетчер: журнал 403', s==403,(s,b))
s,b,_=call('POST','/api/v1/users',{'email':'x@demo.putzplan.de','full_name':'X Y','role':'worker'},token=disp)
chk('диспетчер: создание 403', s==403,(s,b))
s,b,_=call('GET','/api/v1/roles',token=owner); chk('список ролей', s==200 and len(b)>=5,(s,len(b) if isinstance(b,list) else b))
s,b,_=call('POST','/api/v1/roles',{'key':f'objektleiter_{SUFFIX}','name':'Objektleiter','permissions':['planning.view','users.read']},token=owner)
chk('создание роли 201', s==201 and b['permissions_count']==2,(s,b)); role_id=b.get('id')
s,b,_=call('PUT',f'/api/v1/roles/{role_id}/permissions',{'permissions':['planning.view','planning.edit','users.read']},token=owner)
chk('назначение прав роли', s==200 and b['permissions_count']==3,(s,b))
s,b,_=call('PUT',f'/api/v1/roles/{role_id}/permissions',{'permissions':['nonexistent.perm']},token=owner)
chk('неизвестное право 422', s==422 and b['code']=='unknown_permissions',(s,b))
s,b,_=call('GET',f'/api/v1/users/{new_id}/sessions',token=owner); chk('сессии пользователя', s==200,(s,b))
s,b,_=call('POST',f'/api/v1/users/{new_id}/deactivate',{'reason':'ok'},token=owner)
chk('деактивация: причина коротка 422', s==422,(s,b))
s,b,_=call('POST',f'/api/v1/users/{new_id}/deactivate',{'reason':'расторжение договора'},token=owner)
chk('деактивация 200', s==200 and b['status']=='deactivated',(s,b))
s,b,_=call('POST','/api/v1/auth/login',{'email':f'neu-{SUFFIX}@demo.putzplan.de','password':'Neuepass12345'})
chk('деактивированный не входит 403', s==403,(s,b))
ORIGIN='http://localhost:5173'
s,b,_=call('POST','/api/v1/auth/refresh',{},cookies=ck,csrf=csrf_value,origin=ORIGIN)
chk('ротация refresh по cookie', s==200 and 'access_token' in b,(s,b))
s,b,_=call('POST','/api/v1/auth/refresh',{},cookies=ck,csrf=csrf_value,origin=ORIGIN)
chk('повтор старого refresh 409', s in (409,) and b['code'] in ('refresh_reuse','refresh_race'),(s,b))
s,b,_=call('POST','/api/v1/auth/refresh',{},cookies=ck,csrf='fremd',origin=ORIGIN)
chk('CSRF: неверный токен 403', s==403 and b['code']=='csrf_token_mismatch',(s,b))
s,b,_=call('POST','/api/v1/auth/refresh',{},cookies=ck,csrf=csrf_value,origin='https://evil.example.com')
chk('CSRF: чужой Origin 403', s==403 and b['code']=='csrf_origin_rejected',(s,b))
s,b,_=call('GET','/api/v1/me',token=owner)
chk('после отзыва цепочки сессия недействительна', s==401 and b['code']=='session_revoked',(s,b))
s,b,h=call('POST','/api/v1/auth/login',{'email':'owner@demo.putzplan.de','password':'Owner12345678'})
owner=b['access_token']
s,b,_=call('GET','/api/v1/audit-logs?limit=30',token=owner)
actions=[e['action'] for e in b.get('data',[])]
chk('журнал доступен', s==200 and len(actions)>0,(s,len(actions)))
for need in ['LOGIN_SUCCESS','LOGIN_FAILED','USER_CREATED','USER_UPDATED','USER_DEACTIVATED','ROLE_CREATED','ROLE_PERMISSIONS_UPDATED','ACCESS_DENIED','REFRESH_REUSE_DETECTED']:
    chk(f'журнал: {need}', need in actions, actions[:12])
seqs=[e['chain_seq'] for e in b['data']]
chk('chain_seq монотонен', all(seqs[i]>seqs[i+1] for i in range(len(seqs)-1)), seqs[:6])
dump=json.dumps(b,ensure_ascii=False)
chk('в журнале нет паролей и токенов', not any(x in dump for x in ['Owner12345678','password','refresh_token','access_token']))
s,b,_=call('POST','/api/v1/auth/logout-all',{},token=owner); chk('logout-all 200', s==200,(s,b))
s,b,_=call('GET','/api/v1/me',token=owner); chk('после logout-all токен не действует', s==401,(s,b))
f=[r for r in res if not r[1]]
print(f'\nSMOKE: passed={len(res)-len(f)} failed={len(f)}')
raise SystemExit(1 if f else 0)

from core.profiles import ProfileManager
from core.database import Database
import sys

def print_rows(title, rows):
    print(title)
    if not rows:
        print('  <none>')
        return
    for r in rows:
        print('  ', r)

pm = ProfileManager()
profiles = pm.list_profiles()
print('profiles:', profiles)
name = 'Default' if 'Default' in profiles else (profiles[0] if profiles else None)
print('chosen profile:', name)
if not name:
    sys.exit(0)
pm.load_profile(name)
db = Database(pm)
ok = db.connect()
print('db connect ok?', ok)
print('db last_error:', db.last_error)

cid = int(sys.argv[1]) if len(sys.argv) > 1 else 7
print('\nclient id:', cid)

cur = db.cursor
cur.execute("SELECT id,client_id,client_username,date FROM sales ORDER BY id DESC LIMIT 50")
print_rows('recent sales (50):', cur.fetchall())

cur.execute('SELECT id,client_id,client_username,date FROM sales WHERE client_id=%s ORDER BY id DESC', (cid,))
print_rows(f'sales where client_id={cid}:', cur.fetchall())

# resolve username
cur.execute('SELECT username FROM clients WHERE id=%s', (cid,))
cres = cur.fetchone()
username = str(cres[0]) if cres else ''
print('resolved username:', username)
if username:
    norm = db._normalize_exact(username)
    cur.execute("SELECT id,client_id,client_username,date FROM sales WHERE LOWER(REGEXP_REPLACE(COALESCE(client_username,''),'\\\\s+',' ','g')) = LOWER(%s) ORDER BY id DESC", (norm,))
    print_rows(f"sales where client_username matches '{username}':", cur.fetchall())

cur.execute("SELECT a.id,a.entity_type,a.entity_id,a.display_name FROM attachments a JOIN sales s ON a.entity_type='sale' AND a.entity_id=s.id WHERE s.client_id=%s ORDER BY a.id DESC", (cid,))
print_rows('attachments attached to sales by client_id:', cur.fetchall())

cur.execute('SELECT id,entity_type,entity_id,display_name FROM attachments WHERE entity_type=\'client\' AND entity_id=%s ORDER BY id DESC', (cid,))
print_rows('attachments stored on client:', cur.fetchall())

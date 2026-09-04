src = open('ui/tabs/analytics_tab.py', 'r', encoding='utf-8').read()
import re
matches = re.finditer(r'COALESCE\([^)]+\)', src)
for m in matches:
    start = max(0, m.start() - 40)
    end = min(len(src), m.end() + 40)
    print(f'Position {m.start()}: ...{src[start:end]}...')
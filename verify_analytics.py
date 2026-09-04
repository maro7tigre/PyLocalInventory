with open('ui/tabs/analytics_tab.py', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()
# Print lines around period combo initialization
lines = content.split('\n')
for i, line in enumerate(lines):
    if 'period_combo' in line or 'from_date' in line or 'to_date' in line or '_current_period' in line:
        start = max(0, i-1)
        end = min(len(lines), i+5)
        for j in range(start, end):
            print(f'{j+1}: {lines[j]}')
        print('---')
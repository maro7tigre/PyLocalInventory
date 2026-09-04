src = open('core/database.py', 'r', encoding='utf-8', errors='replace').read()
idx = src.find('def get_client_account')
if idx >= 0:
    print(f'Found at index {idx}')
    print(src[idx:idx+800])
else:
    print('Not found')
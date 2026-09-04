import re

with open('report/devis_templet.html', 'r', encoding='utf-8', errors='replace') as f:
    devis = f.read()
with open('report/bdl_templet.html', 'r', encoding='utf-8', errors='replace') as f:
    bdl = f.read()

# Compare document-title font sizes
dev_title = re.search(r'\.document-title \{[^}]+\}', devis)
bdl_title = re.search(r'\.document-title \{[^}]+\}', bdl)

print("Devis document-title:", dev_title.group() if dev_title else "NOT FOUND")
print("BDL document-title:", bdl_title.group() if bdl_title else "NOT FOUND")

# Compare column rules
dev_rules = re.findall(r'\.column-rule\.rule-\d \{[^}]+\}', devis)
bdl_rules = re.findall(r'\.column-rule\.rule-\d \{[^}]+\}', bdl)

print("\nDevis column rules:")
for r in dev_rules:
    print("  ", r)
print("\nBDL column rules:")
for r in bdl_rules:
    print("  ", r)

# Compare table min-height
dev_table = re.search(r'\.table-frame\.fill-page \{[^}]+\}', devis)
bdl_table = re.search(r'\.table-frame\.fill-page \{[^}]+\}', bdl)

print("\nDevis table min-height:", dev_table.group() if dev_table else "NOT FOUND")
print("BDL table min-height:", bdl_table.group() if bdl_table else "NOT FOUND")

# Count table columns
dev_th = devis.count('<th>')
bdl_th = bdl.count('<th>')
print(f"\nDevis <th> count: {dev_th}")
print(f"BDL <th> count: {bdl_th}")
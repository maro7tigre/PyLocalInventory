with open('ui/dialogs/reports_dialog.py', 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()
    # Find lines related to devis/bdl generation
    for i, line in enumerate(lines, 1):
        lower = line.lower()
        if 'devis' in lower or 'bdl' in lower or 'bon de liv' in lower:
            # Print line number and content (trimmed to 150 chars)
            content = lines[i-1].rstrip()[:150]
            print(f'{i}: {content}')
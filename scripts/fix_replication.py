p = r'C:\Users\Marvin\Desktop\Storage Distributed System\vault\services\replication.py'
with open(p, 'r') as f:
    content = f.read()
# Replace actual tab/newline characters in the string with escape sequences
old = 'ch not in "\t\n"'
new = 'ch not in "\\t\\n"'
if old in content:
    content = content.replace(old, new)
    with open(p, 'w') as f:
        f.write(content)
    print('Fixed escape sequences')
else:
    print('Pattern not found, checking file...')
    # Show the relevant line
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'control characters' in line or 'ord(ch)' in line:
            print(f'Line {i+1}: {repr(line)}')
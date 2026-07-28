import re, sys

def clean_vtt(path):
    with open(path, 'r') as f:
        text = f.read()
    
    # Extract only the clean text lines (alternating with timestamps)
    # Lines after a timestamp block with the full text (no <c> tags per line)
    lines = text.split('\n')
    clean_lines = []
    prev_line = ""
    
    for line in lines:
        line = line.strip()
        # Skip headers, timestamps, empty
        if not line or line.startswith('WEBVTT') or line.startswith('Kind:') or line.startswith('Language:'):
            continue
        if '-->' in line or line.startswith('align:'):
            continue
        
        # Strip <c> tags and timestamps
        cleaned = re.sub(r'<[^>]+>', '', line)
        cleaned = re.sub(r'\[&nbsp;__&nbsp;\]', '[inaudible]', cleaned)
        cleaned = cleaned.strip()
        
        if not cleaned:
            continue
        
        # Deduplicate near-duplicate consecutive lines (overlap)
        if prev_line:
            # Check if cleaned is mostly contained in prev_line or vice versa
            if cleaned == prev_line:
                continue
            # Suffix-prefix overlap: if prev suffix matches cleaned prefix
            # Simple approach: just remove exact duplicates and lines fully contained
            if cleaned in prev_line or prev_line in cleaned:
                continue
        
        clean_lines.append(cleaned)
        prev_line = cleaned
    
    return ' '.join(clean_lines)

for arg in sys.argv[1:]:
    outname = arg.replace('.en.vtt', '_cleaned.txt')
    cleaned = clean_vtt(arg)
    with open(outname, 'w') as f:
        f.write(cleaned)
    print(f"Wrote {len(cleaned)} chars to {outname}")


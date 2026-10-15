import os
import json
import urllib.request
from datetime import timedelta
from youtube_transcript_api import YouTubeTranscriptApi

videos = [
    {
        'id': 'nQwJVHCtDDY',
        'file': '01_matt_pocock_david_ondrej.md',
        'custom_label': 'Matt Pocock & David Ondrej: Agentic Engineering Workflow'
    },
    {
        'id': 'xgkjtF89-44',
        'file': '02_dex_matt_nasa_workflow.md',
        'custom_label': 'Dex & Matt: Ex-NASA Dev Agentic Engineering Workflow'
    },
    {
        'id': 'zcLPGC-tvgk',
        'file': '03_uncle_bob_matt_software_fundamentals.md',
        'custom_label': 'Uncle Bob & Matt: Software Fundamentals in the Age of AI'
    },
    {
        'id': 'MN9dGgmLyso',
        'file': '04_poteto_matt_shipping_prs_spacex.md',
        'custom_label': 'Poteto & Matt: Shipping 1,000s of PRs a Month (pstack, SpaceX)'
    },
    {
        'id': '8ZgpAXe5V5w',
        'file': '05_david_kun_chen_l8_principal_setup.md',
        'custom_label': 'David & Kun Chen: L8 Principal Engineer Agentic Setup'
    }
]

out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources')
os.makedirs(out_dir, exist_ok=True)

api = YouTubeTranscriptApi()

def format_ts(seconds):
    td = timedelta(seconds=int(seconds))
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

readme_entries = []

for v in videos:
    vid = v['id']
    filename = v['file']
    filepath = os.path.join(out_dir, filename)
    
    # 1. Fetch metadata via oembed
    oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json"
    req = urllib.request.Request(oembed_url, headers={'User-Agent': 'Mozilla/5.0'})
    title = v['custom_label']
    author = 'Unknown'
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            title = data.get('title', title)
            author = data.get('author_name', author)
    except Exception as e:
        print(f"Metadata error for {vid}: {e}")
        
    print(f"Fetching transcript for [{vid}] {title}...")
    try:
        transcript_data = api.fetch(vid)
    except Exception as e:
        print(f"Error fetching transcript for {vid}: {e}")
        continue
        
    # Group snippets into ~45-60 second paragraph chunks
    chunks = []
    current_chunk = []
    chunk_start = 0.0
    
    for item in transcript_data:
        text = item.text.replace('\n', ' ').strip()
        if not text:
            continue
        if not current_chunk:
            chunk_start = item.start
            current_chunk.append(text)
        else:
            current_chunk.append(text)
            if item.start - chunk_start >= 45.0: # ~45s group
                chunks.append((chunk_start, ' '.join(current_chunk)))
                current_chunk = []
                
    if current_chunk:
        chunks.append((chunk_start, ' '.join(current_chunk)))
        
    # Build markdown
    md_content = []
    md_content.append(f"# {title}\n")
    md_content.append(f"- **Video URL:** https://www.youtube.com/watch?v={vid}")
    md_content.append(f"- **Channel / Host:** {author}")
    md_content.append(f"- **Topic / Reference:** {v['custom_label']}")
    md_content.append(f"- **Total Transcript Chunks:** {len(chunks)}")
    md_content.append(f"- **Raw Snippet Count:** {len(transcript_data)}\n")
    md_content.append("## Transcript\n")
    
    for start_time, text in chunks:
        ts_str = format_ts(start_time)
        md_content.append(f"**[{ts_str}]** {text}\n")
        
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md_content))
        
    readme_entries.append({
        'title': title,
        'author': author,
        'url': f"https://www.youtube.com/watch?v={vid}",
        'file': filename,
        'chunks': len(chunks)
    })
    print(f"Saved {filename} ({len(chunks)} chunks).")

# Generate README.md in resources
readme_lines = [
    "# Resources: Agentic Engineering Video Transcripts\n",
    "Bu dizin, agentic workflow mimarisini optimize etmek ve en iyi pratikleri sentezlemek için toplanan video transkriptlerini içerir.\n",
    "| No | Video Başlığı | Konuşmacılar / Kanal | Link | Dosya |",
    "|---|---|---|---|---|"
]

for idx, e in enumerate(readme_entries, 1):
    readme_lines.append(f"| {idx} | {e['title']} | {e['author']} | [YouTube]({e['url']}) | [{e['file']}]({e['file']}) |")

with open(os.path.join(out_dir, 'README.md'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(readme_lines))

print("Finished generating all transcripts and README.md!")

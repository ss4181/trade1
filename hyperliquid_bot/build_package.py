"""Build a standalone source ZIP using an explicit allowlist; no secrets or raw data."""
import hashlib
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parent
FILES=['.env.example','.gitignore','README.md','RESEARCH_PROTOCOL.md','VALIDATION.md',
       'requirements.txt','start-termux.sh','bot.py','client.py','engine.py',
       'store.py','telegram.py','oi_history.py','research.py','forward.py',
       'test_bot.py','build_package.py','evidence/research.json','evidence/coverage.json',
       'evidence/live-status.json']


def build():
    for name in FILES:
        if not (ROOT/name).is_file():
            raise RuntimeError('Missing package member: '+name)
    target=ROOT/'dist'/'hyperliquid-bot.zip'
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(ROOT/name,'hyperliquid-bot/'+name)
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.sha256').write_text(digest+'  '+target.name+'\n',encoding='ascii')
    print(str(target))
    print('SHA-256: '+digest)


if __name__=='__main__':
    build()

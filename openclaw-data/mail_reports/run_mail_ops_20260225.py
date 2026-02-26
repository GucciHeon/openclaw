import imaplib, email, os, re, json, socket
from email.header import decode_header
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/home/user/.openclaw/workspace/mail_reports')
socket.setdefaulttimeout(20)

FORCE_DELETE = [
    'CJ대한통운 LoIS Parcel 로그인 2차 인증',
    '정산금액 입금 완료 안내입니다.',
    '[롯데렌탈] 02 월 이용대금명세서 입니다',
    'Summary of failures for Google Apps Script: 전체 장부 프로젝트',
]
READ_KEEP = 'RE: Re: [서울신라호텔] 6월 객실 요금 제안드립니다.'


def dmw(s):
    if s is None:
        return ''
    out = ''
    for p, enc in decode_header(s):
        if isinstance(p, bytes):
            for c in ([enc] if enc else []) + ['utf-8','cp949','euc-kr','latin1']:
                if not c: continue
                try:
                    out += p.decode(c, errors='replace'); break
                except Exception:
                    pass
            else:
                out += p.decode('utf-8', errors='replace')
        else:
            out += p
    return out


def parse_boxes(raw):
    boxes=[]
    for line in raw or []:
        try: s=line.decode(errors='replace')
        except: continue
        m=re.match(r'.*\((?P<flags>[^)]*)\)\s+"(?P<sep>.*)"\s+(?P<name>.+)$', s)
        if not m: continue
        name=m.group('name').strip()
        if name.startswith('"') and name.endswith('"'): name=name[1:-1]
        boxes.append((name,m.group('flags')))
    return boxes


def pick_trash(boxes):
    for n,f in boxes:
        if '\\Trash' in f: return n
    cands=['[Gmail]/Trash','Trash','INBOX.Trash','휴지통','Bin','Deleted Messages','Deleted Items']
    lower={n.lower():n for n,_ in boxes}
    for c in cands:
        if c.lower() in lower: return lower[c.lower()]
    for n,_ in boxes:
        nl=n.lower()
        if 'trash' in nl or '휴지통' in nl or 'deleted' in nl: return n
    return None


def fetch_hdr(imap, uid):
    t,d=imap.uid('FETCH', uid, '(RFC822.HEADER)')
    if t!='OK' or not d: return None
    b=None
    for p in d:
        if isinstance(p, tuple) and len(p)>=2 and isinstance(p[1], (bytes,bytearray)):
            b=bytes(p[1]); break
    if not b: return None
    m=email.message_from_bytes(b)
    return {
        'subject': dmw(m.get('Subject','')).strip(),
        'message_id': (m.get('Message-ID','') or '').strip(),
        'from': dmw(m.get('From','')).strip(),
        'date': dmw(m.get('Date','')).strip(),
    }


def uid_search_subject(imap, subj):
    out=set(); clean=subj.replace('"','')
    for charset, q in [(None,f'(SUBJECT "{clean}")'),('UTF-8',f'(SUBJECT "{clean}")')]:
        try:
            if charset:
                t,d=imap.uid('SEARCH','CHARSET',charset,q)
            else:
                t,d=imap.uid('SEARCH',q)
            if t=='OK' and d and d[0]:
                for u in d[0].split():
                    out.add(u.decode() if isinstance(u,bytes) else str(u))
        except Exception:
            pass
    return sorted(out, key=lambda x:int(x) if str(x).isdigit() else str(x))


def load_delete_subjects():
    subs=set(FORCE_DELETE)
    # from manager reports 🗑️ lines
    for f in [BASE/'manager'/'am-final-report.md', BASE/'manager'/'pm-final-report.md']:
        if not f.exists(): continue
        for line in f.read_text(encoding='utf-8', errors='replace').splitlines():
            line=line.strip()
            if line.startswith('🗑️'):
                subs.add(line.replace('🗑️','',1).strip())
    # from ledger deleteCandidates
    led=BASE/'manager'/'mail-followup-ledger.json'
    if led.exists():
        try:
            j=json.loads(led.read_text(encoding='utf-8'))
            for it in j.get('deleteCandidates',[]):
                s=(it.get('subject') or '').strip()
                if s: subs.add(s)
        except Exception:
            pass
    return sorted(subs)


def account_cfgs():
    return [
        {'name':'daum','host':'imap.daum.net','port':993,'user':os.getenv('DAUM_IMAP_USER'),'password':os.getenv('DAUM_IMAP_PASS') or os.getenv('DAUM_IMAP_PASSWORD')},
        {'name':'gmail','host':'imap.gmail.com','port':993,'user':os.getenv('GMAIL_IMAP_USER'),'password':os.getenv('GMAIL_IMAP_PASS') or os.getenv('GMAIL_IMAP_PASSWORD')},
        {'name':'naver','host':os.getenv('NAVER_IMAP_HOST','imap.naver.com'),'port':int(os.getenv('NAVER_IMAP_PORT','993')),'user':os.getenv('NAVER_IMAP_USER'),'password':os.getenv('NAVER_IMAP_PASS') or os.getenv('NAVER_IMAP_PASSWORD')},
    ]


def run_account(cfg, delete_subjects):
    res={
        'account':cfg['name'],'ok':False,'errors':[],'trash':None,
        'delete':{s:{'matched':[],'moved':[],'reason':None} for s in delete_subjects},
        'read_keep':{'title':READ_KEEP,'matched':[],'marked_read':[],'reason':None}
    }
    if not cfg['user'] or not cfg['password']:
        res['errors'].append('credentials missing')
        for s in delete_subjects: res['delete'][s]['reason']='credentials missing'
        res['read_keep']['reason']='credentials missing'
        return res
    imap=None
    try:
        imap=imaplib.IMAP4_SSL(cfg['host'], cfg['port'])
        imap.login(cfg['user'], cfg['password'])
        t,raw=imap.list()
        if t!='OK': raise RuntimeError('LIST failed')
        boxes=parse_boxes(raw)
        trash=pick_trash(boxes)
        if not trash: raise RuntimeError('trash mailbox not found')
        res['trash']=trash
        selectable=[]
        inbox_candidates=['INBOX','Inbox','받은편지함']
        names=[n for n,_ in boxes]
        for c in inbox_candidates:
            if c in names:
                selectable=[c]
                break
        if not selectable:
            for n,f in boxes:
                fl=f.lower(); nl=n.lower()
                if '\\noselect' in fl: continue
                if n==trash: continue
                if 'spam' in nl or 'junk' in nl: continue
                selectable.append(n)

        for box in selectable:
            if imap.select(f'"{box}"', readonly=False)[0] != 'OK':
                continue
            # delete subjects
            for subj in delete_subjects:
                for uid in uid_search_subject(imap, subj):
                    h=fetch_hdr(imap, uid)
                    if not h: continue
                    if h['subject'] == subj:
                        res['delete'][subj]['matched'].append({'mailbox':box,'uid':uid,'message_id':h['message_id'],'from':h['from'],'date':h['date'],'match':'subject_exact'})
            # read-keep subject
            for uid in uid_search_subject(imap, READ_KEEP):
                h=fetch_hdr(imap, uid)
                if not h: continue
                if h['subject'] == READ_KEEP:
                    res['read_keep']['matched'].append({'mailbox':box,'uid':uid,'message_id':h['message_id'],'from':h['from'],'date':h['date'],'match':'subject_exact'})

        # dedupe
        for subj in delete_subjects:
            u={}
            for m in res['delete'][subj]['matched']: u[(m['mailbox'],m['uid'])]=m
            res['delete'][subj]['matched']=list(u.values())
        u={}
        for m in res['read_keep']['matched']: u[(m['mailbox'],m['uid'])]=m
        res['read_keep']['matched']=list(u.values())

        # move to trash
        for subj in delete_subjects:
            ms=res['delete'][subj]['matched']
            if not ms:
                res['delete'][subj]['reason']='exact subject match 없음(보조 매칭 기준값 부족)'
                continue
            for m in ms:
                if imap.select(f'"{m["mailbox"]}"', readonly=False)[0] != 'OK':
                    continue
                tc,_=imap.uid('COPY', m['uid'], f'"{trash}"')
                if tc=='OK':
                    ts,_=imap.uid('STORE', m['uid'], '+FLAGS.SILENT', '(\\Deleted)')
                    if ts=='OK':
                        imap.expunge()
                        res['delete'][subj]['moved'].append(m)
            if ms and not res['delete'][subj]['moved']:
                res['delete'][subj]['reason']='매칭됨, 이동 실패'

        # mark read keep
        rms=res['read_keep']['matched']
        if not rms:
            res['read_keep']['reason']='exact subject match 없음(보조 매칭 기준값 부족)'
        else:
            for m in rms:
                if imap.select(f'"{m["mailbox"]}"', readonly=False)[0] != 'OK':
                    continue
                ts,_=imap.uid('STORE', m['uid'], '+FLAGS.SILENT', '(\\Seen)')
                if ts=='OK':
                    res['read_keep']['marked_read'].append(m)
            if rms and not res['read_keep']['marked_read']:
                res['read_keep']['reason']='매칭됨, 읽음 처리 실패'

        res['ok']=True
    except Exception as e:
        res['errors'].append(str(e))
        for s in delete_subjects:
            if not res['delete'][s]['matched'] and not res['delete'][s]['reason']:
                res['delete'][s]['reason']=f'account error: {e}'
        if not res['read_keep']['matched'] and not res['read_keep']['reason']:
            res['read_keep']['reason']=f'account error: {e}'
    finally:
        if imap:
            try: imap.logout()
            except: pass
    return res


def main():
    delete_subjects=load_delete_subjects()
    results=[run_account(c, delete_subjects) for c in account_cfgs()]
    out={
        'run_at': datetime.now(timezone.utc).isoformat(),
        'delete_subjects': delete_subjects,
        'forced_delete': FORCE_DELETE,
        'read_keep': READ_KEEP,
        'results': results,
    }
    p=BASE/'ops-result-20260225.json'
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(p))

if __name__=='__main__':
    main()

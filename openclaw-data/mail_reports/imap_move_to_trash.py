import imaplib
import email
from email.header import decode_header
import os
import re
import unicodedata
from datetime import datetime, timezone

TARGET_SUBJECTS = [
    "[주간 리포트] 종료 상담이 크게 줄었어요.",
    "-- DO NOT REPLY -- MP ICAM Additional Information",
    "Summary of failures for Google Apps Script: 전체 장부 프로젝트",
]

ACCOUNTS = [
    {"name": "daum", "host": "imap.daum.net", "port": 993, "user": os.getenv("DAUM_IMAP_USER"), "password": os.getenv("DAUM_IMAP_PASS")},
    {"name": "gmail", "host": "imap.gmail.com", "port": 993, "user": os.getenv("GMAIL_IMAP_USER"), "password": os.getenv("GMAIL_IMAP_PASS")},
    {"name": "naver", "host": os.getenv("NAVER_IMAP_HOST", "imap.naver.com"), "port": int(os.getenv("NAVER_IMAP_PORT", "993")), "user": os.getenv("NAVER_IMAP_USER"), "password": os.getenv("NAVER_IMAP_PASS")},
]


def decode_mime_words(s):
    if s is None:
        return ""
    out = ""
    for part, enc in decode_header(s):
        if isinstance(part, bytes):
            for codec in ([enc] if enc else []) + ["utf-8", "cp949", "euc-kr", "latin1"]:
                if not codec:
                    continue
                try:
                    out += part.decode(codec, errors="replace")
                    break
                except Exception:
                    continue
            else:
                out += part.decode("utf-8", errors="replace")
        else:
            out += part
    return out


def parse_mailboxes(raw_lines):
    boxes = []
    for line in raw_lines:
        if not line:
            continue
        s = line.decode(errors="replace")
        m = re.match(r'.*\((?P<flags>[^)]*)\)\s+"(?P<sep>.*)"\s+(?P<name>.+)$', s)
        if not m:
            continue
        flags = m.group("flags")
        name = m.group("name").strip()
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1]
        boxes.append((name, flags))
    return boxes


def pick_trash_mailbox(boxes):
    for name, flags in boxes:
        if "\\Trash" in flags:
            return name
    candidates = ["[Gmail]/Trash", "Trash", "INBOX.Trash", "휴지통", "Bin", "Deleted Messages", "Deleted Items"]
    lower = {name.lower(): name for name, _ in boxes}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    for name, _ in boxes:
        n = name.lower()
        if "trash" in n or "휴지통" in n or "deleted" in n:
            return name
    return None


def fetch_header(imap, uid):
    tf, fd = imap.uid("FETCH", uid, "(RFC822.HEADER)")
    if tf != "OK" or not fd:
        return None
    msg_bytes = None
    for part in fd:
        if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
            msg_bytes = bytes(part[1])
            break
    if not msg_bytes:
        return None
    msg = email.message_from_bytes(msg_bytes)
    return {
        "subject": decode_mime_words(msg.get("Subject", "")),
        "message_id": (msg.get("Message-ID", "") or "").strip(),
        "from": decode_mime_words(msg.get("From", "")),
        "date": decode_mime_words(msg.get("Date", "")),
    }


def normalize_subject(s):
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def subject_matches(actual_subject, target_subject):
    a = normalize_subject(actual_subject)
    t = normalize_subject(target_subject)
    if not a or not t:
        return False
    if a == t:
        return True
    # IMAP 검색/디코딩 오차 대응: 공백/특수문자 차이로 인한 누락 완화
    if t in a or a in t:
        return True
    return False


def search_uids_by_subject(imap, subject):
    uid_set = set()
    cleaned = subject.replace(chr(34), "")
    queries = [
        (None, f'(SUBJECT "{cleaned}")'),
        ("UTF-8", f'(SUBJECT "{cleaned}")'),
    ]
    for charset, q in queries:
        try:
            if charset:
                t, data = imap.uid("SEARCH", "CHARSET", charset, q)
            else:
                t, data = imap.uid("SEARCH", q)
            if t == "OK" and data and data[0]:
                for u in data[0].split():
                    uid_set.add(u.decode() if isinstance(u, bytes) else str(u))
        except Exception:
            pass

    # fallback: SUBJECT 검색 실패 시 최근 메일 스캔으로 보강
    if not uid_set:
        try:
            t_all, data_all = imap.uid("SEARCH", None, "ALL")
            if t_all == "OK" and data_all and data_all[0]:
                all_uids = [u.decode() if isinstance(u, bytes) else str(u) for u in data_all[0].split()]
                for uid in reversed(all_uids[-300:]):
                    h = fetch_header(imap, uid)
                    if not h:
                        continue
                    if subject_matches(h.get("subject", ""), subject):
                        uid_set.add(uid)
        except Exception:
            pass

    return sorted(uid_set, key=lambda x: int(x) if x.isdigit() else x)


def run_account(account):
    res = {"account": account["name"], "errors": [], "trash": None, "items": {s: {"matched": [], "moved": [], "unmatched_reason": None} for s in TARGET_SUBJECTS}}
    if not (account["user"] and account["password"]):
        res["errors"].append("missing credentials")
        for s in TARGET_SUBJECTS:
            res["items"][s]["unmatched_reason"] = "credentials missing"
        return res

    imap = imaplib.IMAP4_SSL(account["host"], account["port"])
    try:
        imap.login(account["user"], account["password"])
        typ, boxes_raw = imap.list()
        if typ != "OK":
            raise RuntimeError("LIST failed")
        boxes = parse_mailboxes(boxes_raw)
        trash = pick_trash_mailbox(boxes)
        res["trash"] = trash
        if not trash:
            raise RuntimeError("trash mailbox not found")

        # 과도한 전체함 스캔 방지: 기본은 INBOX 계열만 대상으로 처리
        selectable = []
        preferred = ["INBOX", "Inbox", "받은편지함"]
        box_names = [n for n, _ in boxes]
        for p in preferred:
            if p in box_names:
                selectable.append(p)
        if not selectable:
            for name, flags in boxes:
                f = flags.lower()
                nl = name.lower()
                if "\\noselect" in f:
                    continue
                if name == trash:
                    continue
                if "spam" in nl or "junk" in nl:
                    continue
                if "all mail" in nl or "important" in nl or "sent" in nl or "draft" in nl:
                    continue
                selectable.append(name)

        for box in selectable:
            t, _ = imap.select(f'"{box}"', readonly=False)
            if t != "OK":
                continue
            for target in TARGET_SUBJECTS:
                candidate_uids = search_uids_by_subject(imap, target)
                for uid in candidate_uids:
                    h = fetch_header(imap, uid)
                    if not h:
                        continue
                    # 제목 정규화 매칭(원문 보존)
                    if subject_matches(h["subject"], target):
                        res["items"][target]["matched"].append({
                            "mailbox": box,
                            "uid": uid,
                            "message_id": h["message_id"],
                            "from": h["from"],
                            "date": h["date"],
                            "subject": h["subject"],
                        })

        # dedupe by mailbox+uid
        for target in TARGET_SUBJECTS:
            uniq = {}
            for m in res["items"][target]["matched"]:
                uniq[(m["mailbox"], m["uid"])] = m
            res["items"][target]["matched"] = list(uniq.values())

        # move
        for target in TARGET_SUBJECTS:
            matches = res["items"][target]["matched"]
            if not matches:
                res["items"][target]["unmatched_reason"] = "subject exact match 없음(보조 매칭용 message-id/uid/발신자+일시 기준값 없음)"
                continue
            for m in matches:
                t, _ = imap.select(f'"{m["mailbox"]}"', readonly=False)
                if t != "OK":
                    continue
                tc, _ = imap.uid("COPY", m["uid"], f'"{trash}"')
                if tc == "OK":
                    ts, _ = imap.uid("STORE", m["uid"], "+FLAGS.SILENT", "(\\Deleted)")
                    if ts == "OK":
                        imap.expunge()
                        res["items"][target]["moved"].append(m)
            if matches and not res["items"][target]["moved"]:
                res["items"][target]["unmatched_reason"] = "매칭됨, 이동 실패"

    except Exception as e:
        res["errors"].append(str(e))
        for s in TARGET_SUBJECTS:
            if not res["items"][s]["matched"] and not res["items"][s]["unmatched_reason"]:
                res["items"][s]["unmatched_reason"] = f"account error: {e}"
    finally:
        try:
            imap.logout()
        except Exception:
            pass

    return res


def main():
    results = [run_account(a) for a in ACCOUNTS]
    print(f"RUN_AT: {datetime.now(timezone.utc).isoformat()}")
    for subject in TARGET_SUBJECTS:
        print("=" * 100)
        print(f"ITEM: {subject}")
        for r in results:
            item = r["items"][subject]
            print(f"- account={r['account']} matched={len(item['matched'])} moved={len(item['moved'])}")
            for m in item["matched"]:
                moved_mark = "Y" if any((x["mailbox"], x["uid"]) == (m["mailbox"], m["uid"]) for x in item["moved"]) else "N"
                print(f"  * moved={moved_mark} mailbox={m['mailbox']} uid={m['uid']} message-id={m['message_id']} from={m['from']} date={m['date']}")
            if item["unmatched_reason"]:
                print(f"  * reason={item['unmatched_reason']}")
            if r["errors"]:
                print(f"  * account_error={' | '.join(r['errors'])}")


if __name__ == "__main__":
    main()

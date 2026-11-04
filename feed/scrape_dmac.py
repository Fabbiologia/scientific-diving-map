#!/usr/bin/env python3
"""Refresh dmac.json from www.dmac-diving.org (the Diving Medical Advisory Committee).

Reads six public pages (home, guidance, about, history, members, courses) and records every
guidance note, workshop report, position statement, third-party article, news item, member and
approved course, with the date each item was first seen by this feed and a change log between
runs. Only the standard library is used, so it runs unchanged on a GitHub Actions runner.

Usage:
  python3 scrape_dmac.py dmac.json            refresh the file in place (keeps first-seen dates)
  python3 scrape_dmac.py --summary dmac.json  print a one-line summary of today's changes

If the guidance page cannot be read the previous file is left untouched and the exit code is 1,
so a broken run never publishes an empty feed. Titles are kept exactly as the site prints them.
"""
import datetime as dt
import hashlib
import html
import json
import re
import sys
import time
import urllib.request

BASE = 'https://www.dmac-diving.org'
UA = 'scientific-diving-map feed (https://github.com/Fabbiologia/scientific-diving-map)'
PAGES = {'home': '/', 'guidance': '/guidance/', 'about': '/about/', 'history': '/about/history.php',
         'members': '/about/members/', 'courses': '/courses/'}
MONTHS = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep',
                                      'oct', 'nov', 'dec'], 1)}
TODAY = dt.date.today().isoformat()


def fetch(path):
    req = urllib.request.Request(BASE + path, headers={'User-Agent': UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as err:  # noqa: BLE001
            if attempt == 2:
                raise RuntimeError(f'{path}: {err}') from err
            time.sleep(5)


def text(fragment):
    """Visible text of an HTML fragment, with entities decoded and whitespace collapsed."""
    s = re.sub(r'<br\s*/?>', ' ', fragment)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s).replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def iso_month(s):
    """'Jul 2025' or 'updated March 2019' -> '2025-07' / '2019-03'; '' when no month is given."""
    m = re.search(r'([A-Za-z]{3})[a-z]*\.?\s+(\d{4})', s or '')
    if not m or m.group(1).lower() not in MONTHS:
        return ''
    return f'{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}'


def absolute(href, page_path):
    if href.startswith('http'):
        return href
    if href.startswith('/'):
        return BASE + href
    folder = page_path.rsplit('/', 1)[0] + '/'
    return BASE + folder + href.lstrip('./')


def cells(row, cls):
    return re.findall(r'<td class="' + cls + r'"[^>]*>(.*?)</td>', row, re.S)


def parse_guidance(page):
    items = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', page, re.S):
        code_cell = cells(row, 'pubcod') or cells(row, 'pubcods')
        if not code_cell:
            continue
        code = text(code_cell[0])
        title = text((cells(row, 'pubtit') or cells(row, 'pubsup') or [''])[0])
        des = [text(c) for c in cells(row, 'pubdes')]
        withdrawn = bool(cells(row, 'pubicos')) or bool(cells(row, 'pubsup'))
        links = re.findall(r'href="([^"]+)"', row)
        own = [l for l in links if l.lower().endswith(('.pdf', '.docx'))]
        rev = next((d.replace('Rev.', '').strip() for d in des if d.startswith('Rev')), '')
        date = next((d for d in des if iso_month(d)), '')
        item = {'id': re.sub(r'[^a-z0-9]+', '-', code.lower()).strip('-'), 'code': code, 'title': title,
                'status': 'withdrawn' if withdrawn else 'current', 'rev': rev,
                'date': iso_month(date), 'date_text': date}
        if 'Checklist' in title:
            item['id'] += '-checklist'
        if withdrawn:
            sup = [l for l in own]
            item['superseded_by'] = text(re.sub(r'.*?</td>', '', row, count=3)).strip() or ''
            if sup:
                item['superseded_by_url'] = absolute(sup[0], PAGES['guidance'])
        elif own:
            item['url'] = absolute(own[0], PAGES['guidance'])
            if code == 'Workshop':
                item['id'] = 'workshop-' + re.sub(r'\D', '', own[0])[-8:]
        items.append(item)
    return items


def parse_list_section(page, start_marker, end_marker, page_path):
    """<li> entries between two markers: link title, href, and the remaining text."""
    block = page.split(start_marker, 1)[-1].split(end_marker, 1)[0]
    out = []
    for li in re.findall(r'<li(?:\s[^>]*)?>(.*?)</li>', block, re.S):
        links = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', li, re.S)
        if not links:
            continue
        href, label = links[0]
        rest = text(re.sub(r'<a[^>]*>.*?</a>', ' ', li, count=1, flags=re.S))
        out.append({'id': href.rsplit('/', 1)[-1].lower(), 'title': text(label), 'url': absolute(href, page_path),
                    'detail': rest, 'date': iso_month(rest)})
    return out


def parse_news(page):
    block = page.split('>N&nbsp;&nbsp;E&nbsp;&nbsp;W&nbsp;&nbsp;S<', 1)[-1]
    block = block.split('E&nbsp;&nbsp;V&nbsp;&nbsp;E', 1)[0]
    out, seen = [], set()
    for li in re.findall(r'<li(?:\s[^>]*)?>((?:(?!<ul).)*?)(?:<ul|</li>)', block, re.S):
        t = text(li)
        if len(t) < 8 or t in seen:
            continue
        seen.add(t)
        href = re.search(r'href="([^"]+)"', li)
        out.append({'id': hashlib.sha1(t.encode()).hexdigest()[:10], 'text': t,
                    'url': absolute(href.group(1), '/') if href else '', 'date': iso_month(t)})
    return out


def parse_members(page):
    """Members, corresponding members and the secretary. The secretary shares the members' list,
    and corresponding members carry their country as plain text in brackets."""
    members, corresponding, secretary = [], [], ''
    head, _, tail = page.partition('Corresponding Members')
    for part, bucket in ((head, members), (tail, corresponding)):
        for li in re.findall(r'<li(?:\s[^>]*)?>(.*?)</li>', part, re.S):
            t = text(li)
            if len(t) < 4 or t.startswith('-') or 'Privacy' in t:
                continue
            role = ''
            m = re.match(r'(Chairman|Vice-Chairman|Secretary)\s*:\s*', t)
            if m:
                role, t = m.group(1), t[m.end():]
            if role == 'Secretary':
                secretary = t
                continue
            span = re.search(r'<span class="country">\s*\(?([^<)]+)\)?\s*</span>', li)
            name, _, affiliation = t.partition(' - ')
            tail_country = re.search(r'\(([^()]+)\)\s*$', affiliation or name)
            country = span.group(1).strip() if span else (tail_country.group(1).strip() if tail_country else '')
            name = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip() if not affiliation else name.strip()
            affiliation = re.sub(r'\s*\([^)]*\)\s*$', '', affiliation).strip()
            bucket.append({'name': name, 'role': role, 'affiliation': affiliation, 'country': country})
    return {'members': members, 'corresponding': corresponding, 'secretary': secretary}


def parse_courses(page):
    out = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', page, re.S):
        name = cells(row, 'crsname')
        if not name:
            continue
        strong = re.findall(r'<strong>(.*?)</strong>', name[0], re.S)
        if not strong:
            continue
        country = text(re.sub(r'<strong>.*?</strong>', ' ', name[0], flags=re.S)).strip('/ ')
        def lines(cell):  # a cell may hold one line per approved level
            return ' / '.join(t for t in (text(x) for x in re.split(r'<br\s*/?>', cell)) if t)
        out.append({'organiser': ' / '.join(text(s) for s in strong), 'country': country,
                    'level': lines((cells(row, 'crsappl') or [''])[0]),
                    'expiry': lines((cells(row, 'crsappx') or [''])[0])})
    return out


def history_text(page):
    body = page.split('A Brief History of DMAC', 1)[-1].split('</td>', 1)[0]
    return text(body)[:3000]


def summarise_changes(old, new):
    """Change-log entries for guidance, statements, articles and news, newest first."""
    log = []
    for key, label in (('guidance', 'guidance'), ('statements', 'statement'), ('articles', 'article'),
                       ('news', 'news')):
        before = {i['id']: i for i in old.get(key, [])}
        for item in new.get(key, []):
            prev = before.get(item['id'])
            name = item.get('code') or item.get('title') or item.get('text', '')
            if prev is None:
                log.append({'date': TODAY, 'kind': 'added', 'section': label, 'id': item['id'], 'what': name})
            elif prev.get('status') != item.get('status') and item.get('status') == 'withdrawn':
                log.append({'date': TODAY, 'kind': 'withdrawn', 'section': label, 'id': item['id'], 'what': name})
            elif (prev.get('rev'), prev.get('date'), prev.get('title')) != (item.get('rev'), item.get('date'), item.get('title')):
                log.append({'date': TODAY, 'kind': 'revised', 'section': label, 'id': item['id'],
                            'what': f"{name}: {prev.get('rev') or 'no rev'} {prev.get('date_text', '')} -> "
                                    f"{item.get('rev') or 'no rev'} {item.get('date_text', '')}".strip()})
        for item in old.get(key, []):
            if item['id'] not in {i['id'] for i in new.get(key, [])}:
                log.append({'date': TODAY, 'kind': 'removed', 'section': label, 'id': item['id'],
                            'what': item.get('code') or item.get('title') or item.get('text', '')})
    return log


def carry_first_seen(old, new):
    for key in ('guidance', 'statements', 'articles', 'news'):
        before = {i['id']: i.get('first_seen', TODAY) for i in old.get(key, [])}
        for item in new.get(key, []):
            item['first_seen'] = before.get(item['id'], TODAY)


def refresh(path):
    try:
        old = json.load(open(path, encoding='utf-8'))
    except (OSError, ValueError):
        old = {}
    pages, errors = {}, {}
    for name, p in PAGES.items():
        try:
            pages[name] = fetch(p)
        except RuntimeError as err:
            errors[name] = str(err)
    if 'guidance' not in pages:
        sys.exit(f'guidance page unreadable, feed left unchanged: {errors}')
    g = pages['guidance']
    new = {
        'source': {'name': 'Diving Medical Advisory Committee (DMAC)', 'url': BASE,
                   'pages': {k: BASE + v for k, v in PAGES.items()}},
        'checked': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'page_updated': (re.search(r'Page updated ([A-Z][a-z]+ \d{4})', g) or [None, ''])[1],
        'guidance': parse_guidance(g),
        'statements': parse_list_section(g, 'name="position"', 'name="external"', PAGES['guidance']),
        'articles': parse_list_section(g, 'name="external"', 'Page updated', PAGES['guidance']),
        'news': parse_news(pages['home']) if 'home' in pages else old.get('news', []),
        'members': parse_members(pages['members']) if 'members' in pages else old.get('members', {}),
        'courses': parse_courses(pages['courses']) if 'courses' in pages else old.get('courses', []),
        'history': history_text(pages['history']) if 'history' in pages else old.get('history', ''),
        'errors': errors,
    }
    if len(new['guidance']) < 20:
        sys.exit(f"only {len(new['guidance'])} guidance rows parsed; site layout may have changed, feed left unchanged")
    carry_first_seen(old, new)
    log = summarise_changes(old, new) if old else []
    new['changelog'] = (log + old.get('changelog', []))[:200]
    new['feed_started'] = old.get('feed_started', TODAY)
    json.dump(new, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    current = sum(1 for i in new['guidance'] if i['status'] == 'current')
    print(f"{path}: {len(new['guidance'])} guidance rows ({current} current), {len(new['statements'])} statements, "
          f"{len(new['articles'])} articles, {len(new['news'])} news items, "
          f"{len(new['members'].get('members', []))} members, {len(new['courses'])} courses; "
          f"{len(log)} change(s); errors: {errors or 'none'}")


def todays_changes(data):
    return [c for c in data.get('changelog', []) if c['date'] == TODAY]


def summary(path):
    """One line for a commit message or issue title: plain ASCII, no quotes."""
    today = todays_changes(json.load(open(path, encoding='utf-8')))
    if not today:
        print('no change')
        return
    line = '; '.join(f"{c['kind']} {c['section']} {c['what']}" for c in today)
    print(re.sub(r'[`"\'\n]', ' ', line)[:150].strip())


def find_item(data, change):
    key = {'guidance': 'guidance', 'statement': 'statements', 'article': 'articles', 'news': 'news'}[change['section']]
    return next((i for i in data.get(key, []) if i['id'] == change['id']), None)


def digest(path, site_url, sample=False):
    """Markdown digest of today's changes, written for forwarding to colleagues.
    With sample=True it fakes three changes from the latest items, to test the alert channel."""
    data = json.load(open(path, encoding='utf-8'))
    today = todays_changes(data)
    when = dt.date.fromisoformat(TODAY).strftime('%-d %B %Y')
    lines = []
    if sample:
        g = sorted([i for i in data['guidance'] if i['status'] == 'current' and i.get('date')],
                   key=lambda i: i['date'], reverse=True)[:2]
        s = sorted([i for i in data['statements'] if i.get('date')], key=lambda i: i['date'], reverse=True)[:1]
        today = [{'kind': 'revised', 'section': 'guidance', 'id': g[0]['id'], 'what': g[0]['code']},
                 {'kind': 'added', 'section': 'guidance', 'id': g[1]['id'], 'what': g[1]['code']},
                 {'kind': 'added', 'section': 'statement', 'id': s[0]['id'], 'what': s[0]['title']}]
        lines = ['**This is a test of the alert channel.** Nothing changed at DMAC; the three items below are the '
                 'latest ones on its list, shown the way a real alert would show new material.', '']
    if not today:
        print('no change')
        return
    lines += [f'DMAC, the Diving Medical Advisory Committee, published or revised the following on '
              f'[www.dmac-diving.org]({BASE}); the feed saw it on {when}.', '']
    for c in today:
        item = find_item(data, c) or {}
        label = item.get('code') or item.get('title') or item.get('text') or c['what']
        if item.get('code') and item.get('title'):
            label += ': ' + item['title']
        meta = ', '.join(x for x in (f"Rev. {item['rev']}" if item.get('rev') else '', item.get('date_text', ''),
                                     item.get('status', '')) if x)
        link = f" ([open]({item['url']}))" if item.get('url') else ''
        lines.append(f"- **{c['kind'].capitalize()}**, {c['section']}: {label}" + (f' ({meta})' if meta else '') + link)
    lines += ['', f'The DMAC card on the map shows the live list: {site_url}#dmac', f'Atom feed for feed readers: {site_url}dmac.xml',
              '', 'Text ready to forward:', '',
              '> DMAC has published or revised diving medical guidance: ' +
              '; '.join((find_item(data, c) or {}).get('code') or c['what'] for c in today) +
              f'. Details and links: {site_url}#dmac']
    print('\n'.join(lines))


def write_atom(path, data, site_url):
    """Atom feed next to the JSON: one entry per listed item, re-dated when the feed sees a change."""
    from xml.sax.saxutils import escape
    latest_change = {}
    for c in data.get('changelog', []):
        latest_change[c['id']] = max(latest_change.get(c['id'], ''), c['date'])
    entries = []
    for key, label in (('guidance', 'Guidance'), ('statements', 'Statement'), ('articles', 'Article'), ('news', 'News')):
        for i in data.get(key, []):
            if i.get('status') == 'withdrawn':
                continue
            base_date = (i.get('date') + '-01') if i.get('date') else i.get('first_seen', TODAY)
            updated = max(base_date, latest_change.get(i['id'], '')) + 'T00:00:00Z'
            title = (i.get('code') + ': ' if i.get('code') else '') + (i.get('title') or i.get('text', ''))
            meta = ', '.join(x for x in (label, f"Rev. {i['rev']}" if i.get('rev') else '', i.get('date_text', ''),
                                         i.get('detail', '')) if x)
            link = i.get('url') or data['source']['pages'].get('guidance', BASE)
            entries.append((updated, f"  <entry>\n    <title>{escape(title)}</title>\n    <link href=\"{escape(link)}\"/>\n"
                                     f"    <id>tag:fabbiologia.github.io,2026:dmac:{escape(i['id'])}</id>\n"
                                     f"    <updated>{updated}</updated>\n    <summary>{escape(meta)}</summary>\n  </entry>"))
    entries.sort(key=lambda e: e[0], reverse=True)
    xml = ('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">\n'
           '  <title>DMAC guidance and statements (via the Scientific Diving Governance Map)</title>\n'
           f'  <link href="{site_url}dmac.xml" rel="self"/>\n  <link href="{BASE}/guidance/"/>\n'
           f'  <id>tag:fabbiologia.github.io,2026:dmac</id>\n  <updated>{data["checked"]}</updated>\n'
           '  <author><name>scientific-diving-map feed</name></author>\n'
           + '\n'.join(e[1] for e in entries[:60]) + '\n</feed>\n')
    xml_path = path[:-5] + '.xml' if path.endswith('.json') else path + '.xml'
    open(xml_path, 'w', encoding='utf-8').write(xml)
    return xml_path, len(entries)


SITE_URL = 'https://fabbiologia.github.io/scientific-diving-map/'

if __name__ == '__main__':
    args = sys.argv[1:]
    if args[:1] == ['--summary']:
        summary(args[1])
    elif args[:1] == ['--digest']:
        digest(args[-1], SITE_URL, sample='--sample' in args)
    elif len(args) == 1:
        refresh(args[0])
        xml_path, n = write_atom(args[0], json.load(open(args[0], encoding='utf-8')), SITE_URL)
        print(f'{xml_path}: Atom feed with {n} entries')
    else:
        sys.exit(__doc__)

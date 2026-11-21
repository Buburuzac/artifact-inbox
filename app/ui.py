"""Server-rendered web UI (no JS needed except a delete confirm)."""
import html
import json
import re
import os
import secrets
import urllib.parse

import nh3
from markdown_it import MarkdownIt
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from . import store

BASE_URL = os.environ.get("INBOX_BASE_URL", "http://localhost:8000").rstrip("/")
_md = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table").enable("strikethrough")
_TAGS = {"p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "pre", "code",
         "em", "strong", "del", "a", "img", "table", "thead", "tbody", "tr", "th", "td", "sup", "sub"}
_ATTRS = {"a": {"href", "title"}, "img": {"src", "alt", "title"}, "th": {"align"}, "td": {"align"}}

CSS = """
:root{--bg:#f6f7f9;--fg:#17202d;--mut:#697586;--card:#fff;--bd:#e3e8ee;--ac:#365ad9;--ac-soft:#edf1ff;--ok:#16724c;--bad:#bd433f;--side:#fff;--shadow:0 8px 30px rgba(27,41,65,.035)}
@media(prefers-color-scheme:dark){:root{--bg:#11151c;--fg:#e8edf5;--mut:#9ca9bb;--card:#1b222d;--bd:#303c4d;--ac:#99acff;--ac-soft:#263457;--ok:#62c997;--bad:#f58e88;--side:#171d26;--shadow:none}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 Inter,ui-sans-serif,system-ui,sans-serif;display:grid;grid-template-columns:256px minmax(0,1fr);min-height:100vh}a{color:var(--ac)}
main{width:min(100%,1020px);margin:0 auto;padding:36px clamp(20px,4vw,56px) 72px}h1{font-size:clamp(1.65rem,3vw,2.2rem);line-height:1.2;letter-spacing:-.035em;margin:0 0 16px}h2{letter-spacing:-.02em}
aside.side{border-right:1px solid var(--bd);background:var(--side);padding:22px 12px;position:sticky;top:0;height:100vh;overflow:auto;display:flex;flex-direction:column;gap:2px}
.brand{display:flex;align-items:center;gap:11px;color:var(--fg);text-decoration:none;font-weight:750;font-size:1rem;letter-spacing:-.02em;padding:4px 10px 20px}.brandmark{display:grid;place-items:center;width:34px;height:34px;border-radius:10px;background:var(--ac);color:#fff;font-size:1.12rem}
.side h3{font-size:.68rem;text-transform:uppercase;letter-spacing:.11em;color:var(--mut);margin:18px 12px 6px;font-weight:700}.side .nav{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:38px;padding:7px 11px;border-radius:9px;color:var(--fg);text-decoration:none;font-size:.92rem;word-break:break-word}.side .nav:hover{background:var(--bg)}.side .nav.on{background:var(--ac-soft);color:var(--ac);font-weight:650}.side .nav span{color:var(--mut);font-size:.8rem;font-variant-numeric:tabular-nums}.side .nav.on span{color:var(--ac)}.side .nav.sub{padding-left:20px}.side .foot{margin-top:auto;border-top:1px solid var(--bd);padding-top:12px}
#navtoggle,label.menu{display:none}
.heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px}.lede{color:var(--mut);margin:-5px 0 20px}.meta{color:var(--mut);font-size:.82rem;margin:3px 0}.sum{margin:9px 0 1px;color:var(--fg)}
nav.tabs,.chips,.bar,.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.bar{margin:16px 0}.row{margin-top:13px}nav.tabs{border-bottom:1px solid var(--bd);margin:16px 0 20px;gap:20px}nav.tabs a{color:var(--mut);text-decoration:none;padding:8px 2px 10px;border-bottom:2px solid transparent;font-size:.89rem}nav.tabs a.on{color:var(--ac);border-color:var(--ac);font-weight:650}
.card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:17px 20px;margin:11px 0;box-shadow:var(--shadow)}.card:hover{border-color:color-mix(in srgb,var(--ac) 28%,var(--bd))}.card.done .t{color:var(--mut)}.t{font-weight:650;font-size:1.06rem;text-decoration:none;color:var(--fg);word-break:break-word;letter-spacing:-.01em}
form{display:inline;margin:0}button,.btn{font:inherit;font-size:.86rem;font-weight:550;padding:7px 12px;border-radius:8px;border:1px solid var(--bd);background:var(--card);color:var(--fg);cursor:pointer;text-decoration:none;display:inline-block}button:hover,.btn:hover{border-color:var(--ac);color:var(--ac)}button.ok,.btn.primary{background:var(--ac);border-color:var(--ac);color:#fff}button.bad{color:var(--bad)}input,select{font:inherit;padding:8px 11px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--fg);max-width:100%}input:focus,select:focus{outline:2px solid var(--ac);outline-offset:1px}
h2.grp{font-size:.85rem;margin:25px 0 8px;color:var(--mut);text-transform:uppercase;letter-spacing:.07em}.doc{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:16px 24px;overflow-wrap:anywhere}.doc img{max-width:100%}.doc pre{overflow:auto;background:var(--bg);padding:12px;border-radius:8px}.doc table{border-collapse:collapse}.doc td,.doc th{border:1px solid var(--bd);padding:5px 9px}
iframe.view,embed.view{width:100%;height:78vh;border:1px solid var(--bd);border-radius:12px;background:#fff}pre.txt{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;padding:12px 0}.empty{color:var(--mut);padding:40px 16px;text-align:center;background:var(--card);border:1px dashed var(--bd);border-radius:14px}.notice{background:var(--ac-soft);color:var(--fg);padding:13px 16px;border-radius:10px;margin:14px 0}.share-link{display:block;overflow-wrap:anywhere;padding:10px 12px;background:var(--bg);border-radius:8px;margin:8px 0}
.public{display:block}.public main{max-width:900px}.public .brand{padding:0;margin-bottom:34px}
@media(max-width:760px){body{display:block}label.menu{display:inline-flex;align-items:center;gap:7px;position:sticky;top:8px;z-index:5;margin:10px 16px 0;padding:7px 12px;border:1px solid var(--bd);border-radius:9px;background:var(--card);cursor:pointer;box-shadow:var(--shadow)}aside.side{display:none;position:static;height:auto;border-right:0;border-bottom:1px solid var(--bd);padding-top:12px}#navtoggle:checked~aside.side{display:flex}main{padding:24px 16px 56px}.heading{flex-wrap:wrap}}
"""

# Injected into served HTML items. Runs in the sandboxed frame (opaque origin, so real storage throws):
# localStorage/sessionStorage become in-memory maps seeded from the server and mirrored to the parent;
# navigator.clipboard.writeText falls back to execCommand when the Clipboard API is blocked.
SHIM = """(function(){var seed=__STATE__,d={};try{d=JSON.parse(seed)||{}}catch(x){}
function mk(persist){var m=persist?d:{};var s={getItem:function(k){return Object.prototype.hasOwnProperty.call(m,k)?m[k]:null},
setItem:function(k,v){m[k]=String(v);sync()},removeItem:function(k){delete m[k];sync()},clear:function(){for(var k in m)delete m[k];sync()},
key:function(i){return Object.keys(m)[i]||null}};Object.defineProperty(s,'length',{get:function(){return Object.keys(m).length}});
function sync(){if(persist)try{parent.postMessage({readState:JSON.stringify(m)},'*')}catch(x){}}return s}
try{Object.defineProperty(window,'localStorage',{value:mk(true),configurable:true});
Object.defineProperty(window,'sessionStorage',{value:mk(false),configurable:true})}catch(x){}
function fb(t){return new Promise(function(ok,no){var a=document.createElement('textarea');a.value=t;a.style.cssText='position:fixed;opacity:0';
document.body.appendChild(a);a.select();var r=false;try{r=document.execCommand('copy')}catch(x){}a.remove();r?ok():no(new Error('copy blocked'))})}
var w=navigator.clipboard&&navigator.clipboard.writeText?navigator.clipboard.writeText.bind(navigator.clipboard):null;
var c={writeText:function(t){return w?w(t).catch(function(){return fb(t)}):fb(t)}};
try{Object.defineProperty(navigator,'clipboard',{value:c,configurable:true})}catch(x){}})();"""

# Parent side: persist the frame's state per item. Only messages from our own iframe are accepted.
BRIDGE = ("(function(){var f=document.getElementById('htmlview'),t;window.addEventListener('message',function(ev){"
          "if(!f||ev.source!==f.contentWindow||!ev.data||typeof ev.data.readState!=='string')return;"
          "var b=ev.data.readState;clearTimeout(t);t=setTimeout(function(){fetch('/state/__ID__',{method:'PUT',"
          "headers:{'Content-Type':'application/json'},body:b,credentials:'same-origin'})},300)})})();")


def e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


SCRIPT = ("document.addEventListener('submit',function(ev){var m=ev.target.getAttribute('data-confirm');"
          "if(m&&!confirm(m))ev.preventDefault()})")


def page(title: str, body: str, status: int = 200, side: str = "", script: str = "", public: bool = False) -> HTMLResponse:
    nonce = secrets.token_urlsafe(12)
    doc = (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
           f"<meta name=viewport content='width=device-width,initial-scale=1'>"
           f"<meta name=color-scheme content='light dark'><title>{e(title)}</title><style>{CSS}</style></head>"
           f"<body{' class=public' if public else ''}>"
           f"{'' if public else '<input type=checkbox id=navtoggle><label class=menu for=navtoggle>&#9776; Menu</label>'}"
           f"{'' if public else side or sidebar()}<main>{body}</main>"
           f"<script nonce='{nonce}'>{SCRIPT}{script}</script></body></html>")
    return HTMLResponse(doc, status_code=status, headers={
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; "
                                   "frame-src 'self'; connect-src 'self'; object-src 'self'; form-action 'self'; "
                                   f"base-uri 'none'; frame-ancestors 'self'; script-src 'nonce-{nonce}'",
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex, nofollow" if public else "noindex"})


def sidebar(tab: str = "", cat: str = "", sort: str = "", project_id: str = "", section: str = "") -> str:
    cnt = store.counts()
    s_arg = sort if sort and sort != "recent" else ""
    status = "".join(
        f"<a class='nav{' on' if t == tab and not cat and not project_id and not section else ''}' href='/{qs(tab=t, sort=s_arg)}'>{label}<span>{cnt[t]}</span></a>"
        for t, label in (("unread", "Unread"), ("done", "Done"), ("all", "All artifacts")))
    view = tab if tab in ("unread", "done", "all") else "unread"
    cats = "".join(
        f"<a class='nav sub{' on' if c['category'] == cat and not project_id else ''}' href='/{qs(tab=view, sort=s_arg, cat=c['category'])}'>"
        f"{e(c['category'])}<span>{c['count']}</span></a>" for c in store.categories(view))
    cats = cats or "<div class=meta style='padding:0 10px'>No categories yet</div>"
    projects = "".join(
        f"<a class='nav sub{' on' if p['id'] == project_id else ''}' href='/projects/{p['id']}'>{e(p['name'])}<span>{p['unread']}</span></a>"
        for p in store.list_projects())
    projects = projects or "<div class=meta style='padding:0 10px'>No projects yet</div>"
    return (f"<aside class=side><a class=brand href=/'><span class=brandmark>▣</span> Artifact inbox</a>"
            f"<h3>Library</h3>{status}"
            f"<h3>Projects</h3><a class='nav{' on' if section == 'projects' else ''}' href=/projects>All projects <span>＋</span></a>{projects}"
            f"<h3>Categories</h3>{cats}"
            f"<div class=foot><a class='nav{' on' if section == 'agents' else ''}' href=/agents>Agents</a>"
            f"<a class='nav{' on' if section == 'settings' else ''}' href=/settings>Settings</a></div></aside>")


def render_markdown(text: str) -> str:
    return nh3.clean(_md.render(text), tags=_TAGS, attributes=_ATTRS,
                     url_schemes={"http", "https", "mailto"}, link_rel="noopener noreferrer nofollow")


def qs(**kw) -> str:
    return "?" + urllib.parse.urlencode({k: v for k, v in kw.items() if v})


def safe_next(v: str | None, default: str = "/") -> str:
    return v if v and v.startswith("/") and not v.startswith("//") and "\\" not in v else default


def card(it: dict, nxt: str) -> str:
    done = it["done"]
    toggle = (f"<form method=post action='/i/{it['id']}/{'undone' if done else 'done'}'>"
              f"<input type=hidden name=next value='{e(nxt)}'>"
              f"<button class={'' if done else 'ok'}>{'Mark unread' if done else 'Mark done'}</button></form>")
    delete = (f"<form method=post action='/i/{it['id']}/delete' "
              f"data-confirm='Delete this item permanently?'>"
              f"<input type=hidden name=next value='{e(nxt)}'><button class=bad>Delete</button></form>")
    summ = f"<div class=sum>{e(it['summary'])}</div>" if it["summary"] else ""
    project = (f" · <a href='/projects/{it['project_id']}'>{e(it['project_name'])}</a>"
               if it.get("project_id") and it.get("project_name") else "")
    return (f"<div class='card{' done' if done else ''}'><a class=t href='/i/{it['id']}'>{e(it['title'])}</a>"
            f"<div class=meta>{e(it['category'])} · {e(it['type'])} · {e(it['source_agent'])} · "
            f"{e(it['created_at'][:16].replace('T', ' '))} UTC{project}{' · done' if done else ''}</div>{summ}"
            f"<div class=row><a class=btn href='/i/{it['id']}'>Open</a>{toggle}{delete}</div></div>")


def index(request: Request) -> Response:
    q = request.query_params
    tab = q.get("tab") if q.get("tab") in ("unread", "done", "all") else "unread"
    sort = "category" if q.get("sort") == "category" else "recent"
    cat = store.norm_category(q["cat"]) if q.get("cat") else ""
    items = store.list_items(tab, cat or None, limit=500, sort=sort)
    here = "/" + qs(tab=tab, sort=sort if sort != "recent" else "", cat=cat)
    sorts = "".join(f"<a class='{'on' if s == sort else ''}' href='/{qs(tab=tab, sort=s if s != 'recent' else '', cat=cat)}'>{label}</a>"
                    for s, label in (("recent", "Newest first"), ("category", "By category")))
    unread_here = sum(1 for i in items if not i["done"])
    bulk = ""
    if tab != "done" and unread_here:
        label = f"Mark all done ({unread_here}{' in ' + e(cat) if cat else ''})"
        bulk = (f"<form method=post action='/bulk/done' data-confirm='Mark {unread_here} item(s) done?'>"
                f"<input type=hidden name=cat value='{e(cat)}'><input type=hidden name=next value='{e(here)}'>"
                f"<button class=ok>{label}</button></form>")
    if not items:
        body_items = "<div class=empty>Nothing here.</div>"
    elif sort == "category":
        out, last = [], None
        for it in items:
            if it["category"] != last:
                last = it["category"]
                n = sum(1 for x in items if x["category"] == last)
                out.append(f"<h2 class=grp>{e(last)} ({n})</h2>")
            out.append(card(it, here))
        body_items = "".join(out)
    else:
        body_items = "".join(card(it, here) for it in items)
    heading = f"{e(cat) if cat else {'unread': 'Unread', 'done': 'Done', 'all': 'All items'}[tab]}"
    return page("artifact-inbox", f"<h1>{heading} <span class=meta>({len(items)})</span></h1>"
                        f"<nav class=tabs>{sorts}</nav><div class=bar>{bulk}</div>{body_items}",
                side=sidebar(tab, cat, sort))


def _share_panel(it: dict) -> str:
    rows = []
    for share in store.list_shares(it["id"]):
        expired = share["expires_at"] and share["expires_at"] <= store.now()
        state = "Revoked" if share["revoked_at"] else "Expired" if expired else "Active"
        action = (f"<form method=post action='/i/{it['id']}/shares/{share['id']}/revoke' "
                  "data-confirm='Revoke this link? Anyone using it will lose access.'>"
                  "<button class=bad>Revoke</button></form>") if state == "Active" else ""
        rows.append(f"<div class=card><b>{state} link</b><div class=meta>Created {e(share['created_at'][:16])} UTC"
                    f" · Expires {e(share['expires_at'][:16]) + ' UTC' if share['expires_at'] else 'never'}</div>"
                    f"<div class=row>{action}</div></div>")
    return (f"<h2 class=grp>Share this artifact</h2><p class=meta>Anyone with a link can read and download this artifact. "
            "Links can be revoked at any time. The secret URL is shown once.</p>"
            f"<form method=post action='/i/{it['id']}/shares' class=bar>"
            "<label for=share-duration>Link expires</label><select id=share-duration name=duration>"
            "<option value=week>In 7 days</option><option value=day>In 24 hours</option>"
            "<option value=month>In 30 days</option><option value=never>Never</option></select>"
            "<button class=ok>Create share link</button></form>"
            + ("".join(rows) if rows else "<div class=empty>No share links yet.</div>"))


def _reader(it: dict, notice: str = "") -> Response:
    me = f"/i/{it['id']}"
    raw = f"/raw/{it['id']}"
    path = store.file_for(it)
    extra = ""
    if it["type"] == "pdf":
        view = (f"<embed class=view src='{raw}#view=FitH' type='application/pdf'>"
                f"<p class=meta>Can't see the PDF? <a href='{raw}?download=1'>Download it</a>.</p>")
    elif it["type"] == "html":
        view = (f"<iframe id=htmlview class=view sandbox='allow-scripts' allow='clipboard-write' "
                f"src='{raw}' title='{e(it['title'])}'></iframe>")
        extra = BRIDGE.replace("__ID__", it["id"])
    else:
        text = path.read_text("utf-8", errors="replace")
        view = (f"<div class=doc>{render_markdown(text)}</div>" if it["type"] == "markdown"
                else f"<div class=doc><pre class=txt>{e(text)}</pre></div>")
    done = it["done"]
    toggle = (f"<form method=post action='{me}/{'undone' if done else 'done'}'><input type=hidden name=next value='{me}'>"
              f"<button class={'' if done else 'ok'}>{'Mark unread' if done else 'Mark done'}</button></form>")
    delete = (f"<form method=post action='{me}/delete' data-confirm='Delete this item permanently?'>"
              f"<input type=hidden name=next value='/'><button class=bad>Delete</button></form>")
    summ = f"<p class=sum>{e(it['summary'])}</p>" if it["summary"] else ""
    project = (f" · <a href='/projects/{it['project_id']}'>{e(it['project_name'])}</a>"
               if it.get("project_id") and it.get("project_name") else "")
    choices = "<option value=''>Unassigned</option>" + "".join(
        f"<option value='{p['id']}'{' selected' if p['id'] == it.get('project_id') else ''}>{e(p['name'])}</option>"
        for p in store.list_projects())
    project_form = (f"<form method=post action='{me}/project' class=bar>"
                    f"<label for=item-project>Project</label><select id=item-project name=project_id>{choices}</select>"
                    "<button>Save project</button></form>")
    head = (f"<p><a href='/'>&larr; Inbox</a></p><h1>{e(it['title'])}</h1>"
            f"<div class=meta>{e(it['category'])} · {e(it['type'])} · {e(it['source_agent'])} · "
            f"{e(it['created_at'][:16].replace('T', ' '))} UTC{project}{' · done' if done else ''}</div>{summ}"
            f"<div class=row>{toggle}<a class=btn href='{raw}?download=1'>Download</a>{delete}</div>"
            f"{project_form}<br>")
    return page(it["title"], notice + head + view + _share_panel(it),
                side=sidebar("all", it["category"], project_id=it.get("project_id") or ""), script=extra)


def reader(request: Request) -> Response:
    it = store.get_item(request.path_params["id"])
    if not it:
        return page("Not found", "<h1>Not found</h1><p><a href=/>Back</a></p>", 404)
    return _reader(it)


async def create_share(request: Request) -> Response:
    form = await _form(request)
    if form is None:
        return Response("cross-origin request refused", 403)
    try:
        _, token = store.create_share(request.path_params["id"], form.get("duration") or "week")
    except store.PushError as exc:
        return page("Share link", f"<h1>Could not create link</h1><p>{e(exc)}</p>", exc.status)
    it = store.get_item(request.path_params["id"])
    url = f"{BASE_URL}/s/{token}"
    notice = ("<div class=notice><b>Share link created</b><div class=meta>Copy it now; it will not be shown again.</div>"
              f"<a class=share-link href='{e(url)}' rel=noreferrer>{e(url)}</a></div>")
    return _reader(it, notice)


async def revoke_share(request: Request) -> Response:
    form = await _form(request)
    if form is None:
        return Response("cross-origin request refused", 403)
    store.revoke_share(request.path_params["id"], request.path_params["share_id"])
    return RedirectResponse(f"/i/{request.path_params['id']}", 303)


async def move_item(request: Request) -> Response:
    form = await _form(request)
    if form is None:
        return Response("cross-origin request refused", 403)
    try:
        item = store.set_project(request.path_params["id"], form.get("project_id") or None)
    except store.PushError as exc:
        return page("Project", f"<h1>Could not move artifact</h1><p>{e(exc)}</p>", exc.status)
    if not item:
        return Response("not found", 404)
    return RedirectResponse(f"/i/{item['id']}", 303)


async def projects(request: Request) -> Response:
    if request.method == "POST":
        form = await _form(request)
        if form is None:
            return Response("cross-origin request refused", 403)
        try:
            project = store.create_project(form.get("name"))
        except store.PushError as exc:
            return page("Projects", f"<h1>Projects</h1><p class=meta>{e(exc)}</p>" + _project_form(), 400)
        return RedirectResponse(f"/projects/{project['id']}", 303)
    rows = "".join(f"<div class=card><a class=t href='/projects/{p['id']}'>{e(p['name'])}</a>"
                   f"<div class=meta>{p['count']} artifacts · {p['unread']} unread</div></div>" for p in store.list_projects())
    return page("Projects", f"<h1>Projects</h1>{_project_form()}{rows or '<div class=empty>No projects yet.</div>'}",
                side=sidebar(section="projects"))


def _project_form() -> str:
    return ("<form method=post class=bar><input name=name required maxlength=120 placeholder='Project name' "
            "aria-label='Project name'><button class=ok>Create project</button></form>")


async def project(request: Request) -> Response:
    p = store.get_project(request.path_params["id"])
    if not p:
        return page("Not found", "<h1>Project not found</h1><p><a href='/projects'>Projects</a></p>", 404)
    tab = request.query_params.get("tab") if request.query_params.get("tab") in ("unread", "done", "all") else "unread"
    items = store.list_items(tab, project_id=p["id"], limit=500)
    tabs = " ".join(f"<a class='{'on' if t == tab else ''}' href='/projects/{p['id']}?tab={t}'>{label}</a>"
                   for t, label in (("unread", "Unread"), ("done", "Done"), ("all", "All")))
    body = "".join(card(it, f"/projects/{p['id']}?tab={tab}") for it in items) or "<div class=empty>Nothing here.</div>"
    return page(p["name"], f"<p><a href='/projects'>&larr; Projects</a></p><h1>{e(p['name'])}</h1>"
                f"<nav class=tabs>{tabs}</nav>{body}", side=sidebar(tab, project_id=p["id"]))


def settings(request: Request) -> Response:
    auth = "Enabled" if os.environ.get("INBOX_UI_PASSWORD") else "Managed by reverse proxy"
    body = ("<h1>Settings</h1><p class=lede>Manage how people and agents access this inbox.</p>"
            f"<div class=card><h2>Public address</h2><p class=meta>Links returned to agents use this address.</p>"
            f"<code>{e(BASE_URL)}</code></div>"
            f"<div class=card><h2>Access</h2><p>Web password: <b>{auth}</b></p>"
            "<p class=meta>API requests require an admin or per-agent bearer token.</p>"
            "<a class=btn href=/agents>Manage agents</a></div>"
            "<div class=card><h2>Sharing</h2><p class=meta>Create a link from an artifact page. "
            "The link grants read and download access to that artifact until it expires or you revoke it.</p>"
            "<a class=btn href='/?tab=all'>Browse artifacts</a></div>"
            "<div class=card><h2>Projects</h2><p class=meta>Agents can send artifacts directly to a project "
            "by passing its ID to the MCP tool or REST API.</p><a class=btn href=/projects>Manage projects</a></div>")
    return page("Settings", body, side=sidebar(section="settings"))


def raw(request: Request) -> Response:
    it = store.get_item(request.path_params["id"])
    if not it:
        return Response("not found", 404)
    return _raw_response(it, bool(request.query_params.get("download")))


def _raw_response(it: dict, download: bool = False, shared: bool = False) -> Response:
    path = store.file_for(it)
    ctype = {"pdf": "application/pdf", "html": "text/html; charset=utf-8",
             "markdown": "text/plain; charset=utf-8", "text": "text/plain; charset=utf-8"}[it["type"]]
    safe = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in it["title"])[:80].strip() or "item"
    fallback = "".join(ch if ch.isascii() and (ch.isalnum() or ch in "-_ .") else "_"
                       for ch in safe).strip(" ._") or "item"
    ext = store.EXT[it["type"]]
    disposition = (f"{'attachment' if download else 'inline'}; filename=\"{fallback}.{ext}\"; "
                   f"filename*=UTF-8''{urllib.parse.quote(f'{safe}.{ext}', safe='')}")
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
               "Content-Disposition": disposition, "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"}
    if it["type"] != "pdf":
        # Untrusted bytes: no scripts, no network, opaque origin even if opened directly.
        headers["Content-Security-Policy"] = ("sandbox; default-src 'none'; style-src 'unsafe-inline'; "
                                              "img-src data:")
    if it["type"] == "html" and not download:
        # Scripts run in an opaque origin (no same-origin, no network): the shim gives them a
        # localStorage backed by the parent page, which persists it per item.
        headers["Content-Security-Policy"] = (
            "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
            "style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
            "img-src data:")
        if not shared:
            html = path.read_text("utf-8", errors="replace")
            state = json.dumps(store.get_state(it["id"])).replace("<", "\\u003c")
            shim = f"<script>{SHIM.replace('__STATE__', state)}</script>"
            m = re.search(r"<head[^>]*>", html, re.I) or re.search(r"<html[^>]*>", html, re.I)
            html = html[:m.end()] + shim + html[m.end():] if m else shim + html
            return Response(html, media_type=ctype, headers=headers)
    return FileResponse(path, media_type=ctype, headers=headers)


def shared_reader(request: Request) -> Response:
    token = request.path_params["token"]
    it = store.shared_item(token)
    if not it:
        return page("Link unavailable", "<h1>Link unavailable</h1><p>This link has expired or was revoked.</p>",
                    404, public=True)
    raw_url = f"/s/{token}/raw"
    if it["type"] == "pdf":
        view = f"<embed class=view src='{raw_url}#view=FitH' type='application/pdf'>"
    elif it["type"] == "html":
        view = f"<iframe class=view sandbox='allow-scripts' src='{raw_url}' title='{e(it['title'])}'></iframe>"
    else:
        content = store.file_for(it).read_text("utf-8", errors="replace")
        view = (f"<div class=doc>{render_markdown(content)}</div>" if it["type"] == "markdown"
                else f"<div class=doc><pre class=txt>{e(content)}</pre></div>")
    summary = f"<p class=lede>{e(it['summary'])}</p>" if it["summary"] else ""
    body = (f"<div class=brand><span class=brandmark>▣</span> Artifact inbox</div>"
            f"<h1>{e(it['title'])}</h1>{summary}<p class=meta>{e(it['type'])} · "
            f"{e(it['created_at'][:16].replace('T', ' '))} UTC</p>"
            f"<div class=bar><a class=btn href='{raw_url}?download=1'>Download</a></div>{view}")
    return page(it["title"], body, public=True)


def shared_raw(request: Request) -> Response:
    it = store.shared_item(request.path_params["token"])
    if not it:
        return Response("not found", 404, headers={"Cache-Control": "no-store"})
    return _raw_response(it, bool(request.query_params.get("download")), shared=True)


async def state(request: Request) -> Response:
    item_id = request.path_params["id"]
    if not store.get_item(item_id):
        return Response("not found", 404)
    if request.method == "PUT":
        origin = request.headers.get("origin")
        if not origin or urllib.parse.urlsplit(origin).netloc != request.headers.get("host"):
            return Response("cross-origin request refused", 403)
        body = await request.body()
        if len(body) > store.MAX_STATE:
            return Response("too large", 413)
        try:
            ok = isinstance(json.loads(body), dict)
        except ValueError:
            ok = False
        if not ok:
            return Response("expected a JSON object", 400)
        store.set_state(item_id, body.decode("utf-8"))
        return Response(status_code=204)
    return Response(store.get_state(item_id), media_type="application/json", headers={"Cache-Control": "no-store"})


async def _form(request: Request):
    # Cheap CSRF guard on top of SSO cookies: same-origin POSTs only.
    origin = request.headers.get("origin")
    if origin and urllib.parse.urlsplit(origin).netloc != request.headers.get("host"):
        return None
    return await request.form()


async def act(request: Request) -> Response:
    form = await _form(request)
    if form is None:
        return Response("cross-origin request refused", 403)
    item_id, action = request.path_params["id"], request.path_params["action"]
    nxt = safe_next(form.get("next"))
    if action == "delete":
        store.delete_item(item_id)
        if nxt.startswith(f"/i/{item_id}"):
            nxt = "/"
    elif action in ("done", "undone"):
        store.set_done(item_id, action == "done")
    return RedirectResponse(nxt, 303)


async def bulk(request: Request) -> Response:
    form = await _form(request)
    if form is None:
        return Response("cross-origin request refused", 403)
    store.mark_all_done(form.get("cat") or None)
    return RedirectResponse(safe_next(form.get("next")), 303)


DOC_DIR = os.environ.get("INBOX_DOC_DIR", "/srv")


def _public_text(rel: str):
    def handler(request: Request) -> Response:
        try:
            body = open(os.path.join(DOC_DIR, rel), encoding="utf-8").read()
        except OSError:
            return Response("not found", 404)
        body = body.replace("https://inbox.example.com", BASE_URL)
        claim = request.query_params.get("claim", "")
        if re.fullmatch(r"[A-Za-z0-9_-]{20,128}", claim):  # GET never consumes the claim; POST /api/claim does
            body = body.replace("<CLAIM_CODE>", claim)
        return Response(body, media_type="text/markdown; charset=utf-8", headers={
            "X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"})
    return handler


def healthz(request: Request) -> Response:
    store.counts()
    return Response("ok", media_type="text/plain")


routes = [
    Route("/", index), Route("/healthz", healthz),
    Route("/install", _public_text("docs/INSTALL.md")), Route("/install/SKILL.md", _public_text("skill/SKILL.md")), Route("/i/{id}", reader), Route("/raw/{id}", raw), Route("/state/{id}", state, methods=["GET", "PUT"]),
    Route("/i/{id}/project", move_item, methods=["POST"]),
    Route("/i/{id}/shares", create_share, methods=["POST"]),
    Route("/i/{id}/shares/{share_id}/revoke", revoke_share, methods=["POST"]),
    Route("/i/{id}/{action}", act, methods=["POST"]), Route("/bulk/done", bulk, methods=["POST"]),
    Route("/projects", projects, methods=["GET", "POST"]), Route("/projects/{id}", project),
    Route("/settings", settings),
    Route("/s/{token}", shared_reader), Route("/s/{token}/raw", shared_raw),
]

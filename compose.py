"""Turn an AI post into a folder: photos + 본문.txt + 미리보기.html (copy buttons).

Nothing here touches Naver. The user pastes into the Naver editor themselves.
"""
import base64
import datetime as dt
import html
import json
import re
from pathlib import Path

import images

ROOT = Path(__file__).with_name("posts")


def _safe(name):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_")[:40] or "post"


def build(post, keyword, folder="", pixabay_key="", log=print, own=None):
    """Find photos, write files. Returns the preview html Path.
    own: list of the user's own photo Paths; image blocks with "photo": n use them."""
    out = ROOT / f"{dt.datetime.now():%Y%m%d_%H%M}_{_safe(post['title'])}"
    out.mkdir(parents=True, exist_ok=True)
    used, blocks, n = set(), [], 0
    for b in post["blocks"]:
        if b["type"] != "image":
            blocks.append(b)
            continue
        n += 1
        if own:
            i = int(b.get("photo") or 0) - 1
            if 0 <= i < len(own) and i not in used:
                used.add(i)
                dst = out / f"사진{n}.jpg"
                dst.write_bytes(Path(own[i]).read_bytes())
                blocks.append({**b, "path": str(dst), "credit": "", "no": n})
            else:
                n -= 1
            continue
        log(f"사진 {n} 찾는 중: {b['text']}")
        ph = images.find_photo(b["text"], keyword, out / f"사진{n}.jpg", folder, pixabay_key, used)
        if ph:
            blocks.append({**b, "path": ph["path"], "credit": ph["credit"], "no": n})
        else:
            n -= 1
            log(f"  -> '{b['text']}' 사진을 못 찾아 그 자리는 건너뜀")
    for i, ph in enumerate(own or []):             # photos the AI left out go at the end
        if i not in used:
            n += 1
            dst = out / f"사진{n}.jpg"
            dst.write_bytes(Path(ph).read_bytes())
            blocks.append({"type": "image", "text": "", "caption": "", "path": str(dst), "credit": "", "no": n})
    links = [b for b in blocks if b["type"] == "link"]     # shop links always go last
    post = {**post, "blocks": [b for b in blocks if b["type"] != "link"] + links}
    (out / "post.json").write_text(json.dumps(post, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "본문.txt").write_text(_plain(post), encoding="utf-8")
    page = out / "미리보기.html"
    page.write_text(_html(post), encoding="utf-8")
    log(f"글 완성: 사진 {n}장 -> {out.name}")
    return page


def _plain(post):
    lines = [post["title"], ""]
    for b in post["blocks"]:
        if b["type"] == "image":
            lines.append(f"[사진{b['no']}] {b.get('caption', '')}" + (f" ({b['credit']})" if b["credit"] else ""))
        elif b["type"] == "heading":
            lines.append(f"■ {b['text']}")
        elif b["type"] == "quote":
            lines.append(f"“{b['text']}”")
        elif b["type"] == "link":
            lines.append(f"{b['text']}\n{b['url']}")
        else:
            lines.append(b["text"])
        lines.append("")
    lines.append(" ".join("#" + t for t in post["tags"]))
    return "\n".join(lines)


def _data_uri(path):
    return "data:image/jpeg;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def _html(post):
    e = html.escape
    parts, seg = [], 0

    def seg_btn():
        nonlocal seg
        seg += 1
        return f'<button class="nocopy seg" onclick="copySeg({seg})">글 복사</button><div class="segment" data-seg="{seg}">'

    parts.append(seg_btn())
    for b in post["blocks"]:
        t = e(b["text"])
        if b["type"] == "image":
            cap = e(b.get("caption", ""))
            credit = e(b.get("credit", ""))
            parts.append("</div>")
            parts.append(
                f'<figure><div class="imgwrap"><img src="{_data_uri(b["path"])}" alt="{cap}">'
                f'<button class="nocopy pic" onclick="copyImg(this)">사진{b["no"]} 복사</button></div>'
                f'<p class="cap" style="text-align:center;color:#888;font-size:13px">{cap}'
                + (f'<br><span style="font-size:11px">{credit}</span>' if credit else "")
                + "</p></figure>")
            parts.append(seg_btn())
        elif b["type"] == "heading":
            parts.append(f'<p><br></p><p><b><span style="font-size:19px">{t}</span></b></p>')
        elif b["type"] == "quote":
            parts.append(f'<blockquote><p>{t}</p></blockquote>')
        elif b["type"] == "link":       # shop link on its own line -> Naver turns it into a link card
            u = e(b["url"])
            parts.append(f'<p><b>{t}</b></p><p><a href="{u}">{u}</a></p>'
                         f'<button class="nocopy linkbtn" onclick="copyText(\'{u}\',\'쇼핑 링크\')">🔗 링크만 복사 '
                         f'(네이버 앱 [링크] 버튼에 붙여넣기)</button><p><br></p>')
        elif b["type"] == "notice":
            parts.append(f'<p><span style="font-size:13px;color:#888">{t}</span></p><p><br></p>')
        else:
            parts.append(f"<p>{t}</p><p><br></p>")   # 문단 사이 빈 줄 (블로그 글처럼)
    parts.append("</div>")
    tags = " ".join("#" + e(t) for t in post["tags"])
    body = "\n".join(parts)
    opts = [o for o in post.get("title_options", []) if o.strip() and o.strip() != post["title"]][:3]
    options = "".join(
        f'<li><span>{e(o)}</span> <button class="nocopy" onclick="copyText(this.previousElementSibling.innerText,\'제목\')">이 제목 복사</button></li>'
        for o in opts)
    options = f'<div class="opts"><b>다른 후킹 제목 후보</b><ul>{options}</ul></div>' if options else ""
    return (PAGE.replace("{{TITLE}}", e(post["title"])).replace("{{OPTIONS}}", options)
            .replace("{{BODY}}", body).replace("{{TAGS}}", tags))


PAGE = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><title>{{TITLE}}</title>
<style>
 body{margin:0;background:#f4f5f7;font-family:'Malgun Gothic',sans-serif;color:#222}
 .bar{position:sticky;top:0;background:#03c75a;color:#fff;padding:10px 16px;z-index:9;box-shadow:0 2px 6px #0002}
 .bar button{font:inherit;font-weight:bold;padding:8px 14px;margin-right:6px;border:0;border-radius:6px;cursor:pointer;background:#fff;color:#03a14a}
 .bar small{display:block;margin-top:6px;opacity:.95;line-height:1.5}
 #msg{font-weight:bold;margin-left:8px}
 main{max-width:760px;margin:24px auto;background:#fff;padding:36px 48px;border-radius:8px}
 h1{font-size:28px;font-weight:normal;margin:0 0 24px;padding-bottom:16px;border-bottom:1px solid #eee}
 #post p{font-size:16px;line-height:1.9;margin:0 0 6px}
 figure{margin:22px 0}
 .imgwrap{position:relative;text-align:center}
 .imgwrap img{max-width:100%;border-radius:4px}
 blockquote{border-left:4px solid #03c75a;margin:16px 0;padding:4px 16px;color:#555}
 .nocopy{font:12px 'Malgun Gothic';cursor:pointer;border:1px solid #03c75a;background:#fff;color:#03a14a;border-radius:12px;padding:3px 10px}
 .pic{position:absolute;top:10px;right:10px}
 .seg{margin:8px 0}
 .tags{color:#03a14a;margin-top:24px}
 .opts{background:#f3fbf6;border:1px dashed #03c75a;border-radius:6px;padding:8px 14px;margin:-8px 0 24px;font-size:14px}
 .opts ul{margin:6px 0 0;padding-left:18px}.opts li{margin:4px 0}
 @media(max-width:640px){main{margin:0;padding:18px 16px;border-radius:0}h1{font-size:22px}.bar{padding:8px 10px}.bar button{padding:7px 9px;margin:2px 2px 2px 0;font-size:13px}.bar small{display:none}}
</style></head><body>
<div class="bar">
 <button onclick="copyText(document.querySelector('h1').innerText,'제목')">① 제목 복사</button>
 <button onclick="copyAll()">② 본문 전체 복사 (사진 포함)</button>
 <button onclick="copyText(document.querySelector('.tags').innerText,'태그')">③ 태그 복사</button>
 <button onclick="savePics()">📥 사진 한번에 저장</button>
 <button id="shareBtn" onclick="sharePics()" style="display:none">📤 블로그 앱으로 사진 보내기</button>
 <span id="msg"></span>
 <small>네이버 블로그 [글쓰기] → 제목 칸에 ① 붙여넣기 → 본문 칸 클릭 후 ② 붙여넣기(Ctrl+V) → 발행할 때 태그 칸에 ③.<br>
 폰: [📥 사진 한번에 저장] → 네이버 앱 사진 버튼 → 갤러리 'Download' 앨범에서 번호 순서대로 여러 장 한꺼번에 선택.</small>
</div>
<main>
 <h1>{{TITLE}}</h1>
 {{OPTIONS}}
 <div id="post">
{{BODY}}
 </div>
 <p class="tags">{{TAGS}}</p>
</main>
<script>
function msg(t){const m=document.getElementById('msg');m.textContent=t;clearTimeout(m._t);m._t=setTimeout(()=>m.textContent='',4000)}
function clean(node){const c=node.cloneNode(true);c.querySelectorAll('.nocopy').forEach(x=>x.remove());
  c.querySelectorAll('.segment,.imgwrap,figure').forEach(x=>{while(x.firstChild)x.parentNode.insertBefore(x.firstChild,x);x.remove()});return c}
async function putHtml(h,txt){
  try{await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([h],{type:'text/html'}),'text/plain':new Blob([txt],{type:'text/plain'})})]);return true}
  catch(e){const d=document.createElement('div');d.contentEditable=true;d.innerHTML=h;d.style.position='fixed';d.style.left='-9999px';document.body.appendChild(d);
    const r=document.createRange();r.selectNodeContents(d);const s=getSelection();s.removeAllRanges();s.addRange(r);const ok=document.execCommand('copy');s.removeAllRanges();d.remove();return ok}}
async function copyText(t,what){
  try{await navigator.clipboard.writeText(t)}catch(e){const a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();document.execCommand('copy');a.remove()}
  msg(what+' 복사됨')}
async function copyAll(){const c=clean(document.getElementById('post'));msg(await putHtml(c.innerHTML,c.innerText)?'본문(사진 포함) 복사됨 → 네이버 본문에 Ctrl+V':'복사 실패 - 글/사진 버튼으로 하나씩 복사하세요')}
async function copySeg(n){const c=clean(document.querySelector('.segment[data-seg="'+n+'"]'));msg(await putHtml(c.innerHTML,c.innerText)?'글 '+n+' 복사됨':'복사 실패')}
async function copyImg(btn){const img=btn.parentNode.querySelector('img');const cv=document.createElement('canvas');cv.width=img.naturalWidth;cv.height=img.naturalHeight;
  cv.getContext('2d').drawImage(img,0,0);
  // pass a Promise so the write starts inside the click (keeps clipboard permission)
  const blob=new Promise(r=>cv.toBlob(r,'image/png'));
  try{await navigator.clipboard.write([new ClipboardItem({'image/png':blob})]);msg(btn.textContent.replace(' 복사','')+' 복사됨 → 네이버 본문 그 자리에 Ctrl+V')}
  catch(e){console.log(e);
    // fallback: copy as html <img> (works in most editors)
    const ok=await putHtml('<img src="'+img.src+'">','');msg(ok?btn.textContent.replace(' 복사','')+' 복사됨 → Ctrl+V':'사진 복사 실패 - 글 폴더의 사진 파일을 끌어다 놓으세요')}}
function picFiles(){const name=(document.querySelector('h1').innerText.replace(/[^\w가-힣]+/g,'_').slice(0,20))||'photo';
  return [...document.querySelectorAll('#post img')].map((im,i)=>{const [h,b]=im.src.split(',');const bin=atob(b),u=new Uint8Array(bin.length);
    for(let k=0;k<bin.length;k++)u[k]=bin.charCodeAt(k);
    return new File([u],name+'_'+String(i+1).padStart(2,'0')+'.jpg',{type:(h.match(/data:([^;]+)/)||[,'image/jpeg'])[1]})})}
async function savePics(){const fs=picFiles();if(!fs.length){msg('사진이 없어요');return}
  for(let i=0;i<fs.length;i++){const a=document.createElement('a');a.href=URL.createObjectURL(fs[i]);a.download=fs[i].name;
    document.body.appendChild(a);a.click();a.remove();msg('사진 저장 중 '+(i+1)+'/'+fs.length);await new Promise(r=>setTimeout(r,600))}
  msg('사진 '+fs.length+'장 저장됨 → 갤러리 Download 앨범 (여러 번 다운로드 허용을 물으면 [허용])')}
async function sharePics(){const fs=picFiles();try{await navigator.share({files:fs});msg('보냈어요')}catch(e){if(e.name!=='AbortError')msg('보내기 실패 - [사진 한번에 저장]을 쓰세요')}}
try{if(navigator.canShare&&navigator.canShare({files:[new File([new Uint8Array(1)],'a.jpg',{type:'image/jpeg'})]}))document.getElementById('shareBtn').style.display=''}catch(e){}
</script></body></html>
"""

# Plan: Platform-styled social preview cards in Post Viewer

## Goal
Replace the plain `<pre class="post-copy">` blocks in `posts.html` with platform-styled preview cards that visually mimic each social platform's actual post appearance.

## Files to modify
Only: `/root/pulseops-studio/dashboard/templates/posts.html`

Do NOT touch app.py, queue_db.py, pipeline.py, or any other file.

---

## Platform card designs

### LinkedIn (Brand + Personal) — mimic a LinkedIn post card

```html
<div class="lk-card">
  <div class="lk-header">
    <div class="lk-avatar">PO</div>
    <div class="lk-meta">
      <strong>PulseOps</strong>         <!-- brand -->
      <!-- OR for personal: <strong>Jon Skalski</strong> -->
      <span>Operations Consulting · 1st</span>
      <span>Just now · 🌐</span>
    </div>
  </div>
  <div class="lk-body">{{ copy text here }}</div>
  <div class="lk-footer">
    <span>👍 Like</span>
    <span>💬 Comment</span>
    <span>🔁 Repost</span>
    <span>✉️ Send</span>
  </div>
</div>
```

CSS for `.lk-card`:
```css
.lk-card {
  background: #1b1f2e;
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  padding: 16px;
  margin-top: 12px;
  font-size: 14px;
  line-height: 1.6;
}
.lk-header {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}
.lk-avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--gradient);
  display: grid;
  place-items: center;
  font-weight: 900;
  font-size: 13px;
  flex-shrink: 0;
}
.lk-meta strong { display: block; font-size: 14px; color: var(--text); }
.lk-meta span { display: block; font-size: 12px; color: var(--faint); }
.lk-body {
  color: var(--muted);
  white-space: pre-wrap;
  word-break: break-word;
  margin-bottom: 14px;
}
.lk-footer {
  display: flex;
  gap: 20px;
  color: var(--faint);
  font-size: 12px;
  font-weight: 600;
  border-top: 1px solid rgba(255,255,255,0.08);
  padding-top: 10px;
}
```

Brand LinkedIn uses avatar initials "PO" and name "PulseOps".
Personal LinkedIn uses avatar initials "JS" and name "Jon Skalski".

---

### Instagram — mimic an Instagram post card

```html
<div class="ig-card">
  <div class="ig-header">
    <div class="ig-avatar">PO</div>
    <div>
      <strong>pulseops.us</strong>
      <span>Sponsored</span>
    </div>
    <span style="margin-left:auto;color:var(--faint)">···</span>
  </div>
  <!-- image if present -->
  <img src="{{ post.instagram_image_url }}" ...>
  <div class="ig-actions">
    <span>🤍</span><span>💬</span><span>↗</span>
    <span style="margin-left:auto">🔖</span>
  </div>
  <div class="ig-caption">
    <strong>pulseops.us</strong> {{ caption text }}
  </div>
</div>
```

CSS for `.ig-card`:
```css
.ig-card {
  background: #1b1f2e;
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  overflow: hidden;
  margin-top: 12px;
  font-size: 14px;
}
.ig-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
}
.ig-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: linear-gradient(45deg, #f09433, #e6683c, #dc2743, #cc2366, #bc1888);
  display: grid;
  place-items: center;
  font-weight: 900;
  font-size: 11px;
  flex-shrink: 0;
}
.ig-header strong { display: block; font-size: 13px; color: var(--text); }
.ig-header span { font-size: 11px; color: var(--faint); }
.ig-card img { width: 100%; display: block; }
.ig-actions {
  display: flex;
  gap: 14px;
  padding: 10px 14px;
  font-size: 20px;
}
.ig-caption {
  padding: 0 14px 14px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.ig-caption strong { color: var(--text); margin-right: 6px; }
```

---

### Bluesky — mimic a Bluesky post card

```html
<div class="bsky-card">
  <div class="bsky-header">
    <div class="bsky-avatar">PO</div>
    <div>
      <strong>PulseOps</strong>
      <span>@pulseops.us</span>
    </div>
    <span style="margin-left:auto;color:var(--faint);">🦋</span>
  </div>
  <div class="bsky-body">{{ post text }}</div>
  <div class="bsky-footer">
    <span>💬 Reply</span>
    <span>🔁 Repost</span>
    <span>❤️ Like</span>
  </div>
</div>
```

CSS:
```css
.bsky-card {
  background: #1b1f2e;
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  padding: 16px;
  margin-top: 12px;
  font-size: 14px;
}
.bsky-header {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin-bottom: 10px;
}
.bsky-avatar {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  background: linear-gradient(135deg, #0085ff, #00c6ff);
  display: grid;
  place-items: center;
  font-weight: 900;
  font-size: 12px;
  flex-shrink: 0;
}
.bsky-header strong { display: block; font-size: 14px; color: var(--text); }
.bsky-header span { font-size: 12px; color: var(--faint); }
.bsky-body {
  color: var(--muted);
  white-space: pre-wrap;
  word-break: break-word;
  margin-bottom: 12px;
  line-height: 1.6;
}
.bsky-footer {
  display: flex;
  gap: 18px;
  color: var(--faint);
  font-size: 12px;
  font-weight: 600;
}
```

---

## What to change in posts.html

Replace each social variant's rendering with its platform card. The `<details>` wrapper stays. The `<summary>` label and Copy button stay. Only the content inside the `<details>` after the `<summary>` changes.

**LinkedIn Brand** — replace `<pre class="post-copy">` with `.lk-card` (name: PulseOps, initials: PO)

**LinkedIn Personal** — replace `<pre class="post-copy">` with `.lk-card` (name: Jon Skalski, initials: JS)

**Instagram** — replace the existing `<img>` + `<pre>` with `.ig-card` containing the image inside the card and caption below it

**Bluesky** — replace `<pre class="post-copy">` with `.bsky-card`

## Notes
- All CSS goes in the existing `<style>` block at the top of the template
- Keep all existing functionality: copy buttons, details/summary expand, regenerate
- The copy button should still copy the raw text (not the HTML)
- Do not change any Python, only the template
- Verify the template renders by checking Jinja2 syntax is valid

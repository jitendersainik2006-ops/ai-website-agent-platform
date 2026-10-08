(() => {
  const script = document.currentScript;
  const key = script?.dataset.widgetKey;
  if (!key) return;
  const root = new URL(script.src).origin;
  const launcher = document.createElement('button');
  launcher.type = 'button'; launcher.setAttribute('aria-label', 'Open website assistant');
  launcher.innerHTML = '<span>AI</span><b>Ask us</b>';
  launcher.style.cssText = 'position:fixed;right:20px;bottom:20px;z-index:2147483646;align-items:center;background:#79d9c8;border:1px solid #a0eee1;border-radius:8px;box-shadow:0 14px 34px #0005;color:#09221f;cursor:pointer;display:flex;font-family:Inter,system-ui,sans-serif;font-size:13px;font-weight:800;gap:9px;padding:11px 14px;';
  const frame = document.createElement('iframe');
  frame.src = new URL('/widget-frame.html?widget_key=' + encodeURIComponent(key), script.src).href;
  frame.title = 'Website assistant'; frame.setAttribute('aria-label', 'Website assistant');
  frame.style.cssText = 'position:fixed;right:18px;bottom:18px;width:390px;height:600px;border:0;z-index:2147483647;max-width:calc(100vw - 24px);max-height:calc(100vh - 24px);opacity:0;pointer-events:none;transform:translateY(12px);transition:opacity .18s ease,transform .18s ease;';
  const setOpen = open => { frame.style.opacity = open ? '1' : '0'; frame.style.pointerEvents = open ? 'auto' : 'none'; frame.style.transform = open ? 'translateY(0)' : 'translateY(12px)'; launcher.style.display = open ? 'none' : 'flex'; };
  launcher.onclick = () => setOpen(true);
  window.addEventListener('message', event => { if (event.origin === root && event.data === 'signaldesk:close') setOpen(false); });
  document.body.append(launcher, frame);
})();

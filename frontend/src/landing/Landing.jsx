// Static landing page. Demo facts below are copied from GET /api/demos and the
// precomputed demo files (backend/data/demos/*.json); update them if a demo is re-run.
// ponytail: hardcoded instead of fetched, so the page has no loading or error state to design.
const GITHUB = "https://github.com/mihirargulkar/tastetest";
const DEVPOST = "https://qloo.devpost.com";

const DEMOS = [
  { slug: "matcha-yuzu", title: "Matcha-yuzu cold brew", note: "Bright, citrusy, aimed at a younger crowd", top: "Cupertino Main", rho: "0.90", weakest: "Matcha" },
  { slug: "maple-oat", title: "Brown-butter maple oat latte", note: "Cozy, nostalgic, fall comfort", top: "Civic Center", rho: "0.88", weakest: "Oatmilk Latte" },
  { slug: "smoky-tonic", title: "Smoky cold brew tonic", note: "Bold, smoked-citrus finish, for the after-work crowd", top: "Civic Center", rho: "0.75", weakest: "Cold Brew" },
];

function OpenTool({ className = "btn" }) {
  return <a className={className} href="/app/">Open the tool</a>;
}

export default function Landing() {
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="nav">
        <div className="wrap nav-row">
          <a className="wordmark" href="/">TasteTest</a>
          <nav aria-label="Primary">
            <a href="#how">How it works</a>
            <a href="#score">The score</a>
            <a href={GITHUB}>Source on GitHub</a>
          </nav>
          <OpenTool className="btn btn-sm" />
        </div>
      </header>

      <main id="main">
        <section className="hero wrap" aria-labelledby="hero-title">
          <h1 id="hero-title" className="rise">Know where to test your next drink, and why.</h1>
          <div className="hero-row">
            <div className="hero-copy">
              <p className="lede rise">
                TasteTest scores every store on local demand for the drink's ingredients, using Qloo taste data.
              </p>
              <div className="ctas rise">
                <OpenTool />
                <a className="btn btn-ghost" href="#how">How it works</a>
              </div>
            </div>
            <figure className="hero-shot rise">
              <img src="/landing/tool-matcha-yuzu.webp" width="2000" height="1250" fetchPriority="high"
                alt="The TasteTest tool scoring the matcha-yuzu cold brew demo: a map of 40 stores in the Bay Area and LA basin colored by score, the taste signature on the left and a ranked list of stores to test and skip on the right." />
            </figure>
          </div>
        </section>

        <section className="band" aria-labelledby="who-title">
          <div className="wrap">
            <h2 id="who-title" className="statement">
              Built for specialty coffee chains with <span className="num">15 to 70</span> stores, several cities and no data team, choosing where a limited-time drink gets tested.
            </h2>
          </div>
        </section>

        <section id="how" className="wrap section" aria-labelledby="how-title">
          <h2 id="how-title" className="h2">From one sentence to a test plan.</h2>
          <div className="bento">
            <article className="cell cell-describe reveal">
              <h3>Describe the drink.</h3>
              <p>Plain words are enough. The matcha-yuzu demo starts from this line:</p>
              <blockquote>“Matcha-yuzu cold brew: bright, citrusy, aimed at a younger crowd”</blockquote>
            </article>
            <article className="cell cell-signature reveal">
              <div className="cell-text">
                <h3>Claude turns it into a taste signature.</h3>
                <p>The agent picks real Qloo dish and drink tags that have local data. A word with no match gets the closest concept, and the swap is shown.</p>
              </div>
              <img src="/landing/signature.webp" width="680" height="486" loading="lazy"
                alt="The taste signature for the matcha-yuzu demo: Matcha and Cold Brew, then yuzu swapped for Yuzu Sorbet and Yuzu Cheesecake, and matcha swapped for Matcha Ice Cream, above the Score 40 stores button." />
            </article>
            <article className="cell cell-map reveal">
              <div className="cell-text">
                <h3>40 stores, scored from Qloo heatmaps.</h3>
                <p>Philz Coffee's stores in the Bay Area and the LA basin. The map shows where to test and where to skip.</p>
              </div>
              <img src="/landing/bay-area-map.webp" width="1360" height="1620" loading="lazy"
                alt="Map of the Bay Area stores for the matcha-yuzu demo. Greener dots score higher and redder dots lower. Cupertino Main, the top store, is highlighted." />
            </article>
            <article className="cell cell-brief reveal">
              <div className="cell-text">
                <h3>Open any store for its brief.</h3>
                <p>A verdict, what drives the score, local taste tags, and nearby collab partners: bakeries, dessert shops, tea houses, bookstores and ice cream shops.</p>
              </div>
              <img src="/landing/store-brief.webp" width="760" height="1492" loading="lazy"
                alt="Store brief for Cupertino Main: a test-here verdict, the concepts driving its score against the chain average, local taste tags and three nearby collab partners." />
            </article>
          </div>
        </section>

        <section id="demos" className="wrap section" aria-labelledby="demos-title">
          <h2 id="demos-title" className="h2">Three drinks, already scored.</h2>
          <p className="body">Each one opens in the tool with its map, rankings and store briefs loaded.</p>
          <ul className="demos">
            {DEMOS.map((d) => (
              <li key={d.slug} className="reveal">
                <a className="demo" href={`/app/?demo=${d.slug}`}>
                  <span className="demo-title">{d.title}</span>
                  <span className="demo-note">{d.note}</span>
                  <span className="demo-stat"><span className="k">Top store</span> {d.top}</span>
                  <span className="demo-stat"><span className="k">Lowest ρ</span> <span className="num">{d.rho}</span></span>
                </a>
              </li>
            ))}
          </ul>
        </section>

        <section id="score" className="wrap section" aria-labelledby="score-title">
          <h2 id="score-title" className="h2">What the score means.</h2>
          <p className="statement statement-sm">
            The score is local demand for the drink's ingredients, relative to the rest of the chain. It is not a sales forecast.
          </p>
          <div className="notes">
            <div className="note">
              <h3>A stability check on every ranking</h3>
              <p>The ranking is recomputed with each concept left out in turn. Spearman ρ shows whether the order holds, or hangs on one concept.</p>
              <dl className="rho">
                {DEMOS.map((d) => (
                  <div key={d.slug}>
                    <dt>{d.title}</dt>
                    <dd><span className="num">ρ {d.rho}</span> without {d.weakest}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <div className="note">
              <h3>Why it is called demand</h3>
              <p>In the Qloo API used here, heatmap affinity largely tracks local popularity. So the score is framed as demand, and the tool labels it that way under the map.</p>
            </div>
          </div>
        </section>
      </main>

      <footer className="foot">
        <div className="wrap">
          <div className="foot-cta">
            <p className="statement statement-sm">See where your drink would test first.</p>
            <OpenTool />
          </div>
          <div className="foot-fine">
            <p>Not affiliated with Philz Coffee.</p>
            <p>Built for the <a href={DEVPOST}>Qloo Agentic Hackathon</a>.</p>
            <p>Open source, MIT. <a href={GITHUB}>Source on GitHub</a></p>
          </div>
        </div>
      </footer>
    </>
  );
}

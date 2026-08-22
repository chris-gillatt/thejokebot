const DATA_URL = "data/metrics.json";
const EMBED_SCRIPT_URL = "https://embed.bsky.app/static/embed.js";
const colours = ["#087fdb", "#df6255", "#138a78", "#e9aa31", "#08a9cf"];
const charts = {};
let metrics;
let selectedRange = "30";

const numberFormat = new Intl.NumberFormat("en-GB");
const percentageFormat = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 });
const compactFormat = new Intl.NumberFormat("en-GB", {
  notation: "compact",
  maximumFractionDigits: 1,
});
const dateFormat = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});
const dateTimeFormat = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
  timeZoneName: "short",
});

function setText(id, value) {
  document.getElementById(id).textContent = value;
}

function metricText(value) {
  return value == null ? "--" : numberFormat.format(value);
}

function renderProfile() {
  const profileLink = document.getElementById("profile-link");
  profileLink.href = metrics.account.profile_url;
  document.getElementById("profile-avatar").src = metrics.account.avatar;
  setText("profile-handle", `@${metrics.account.handle}`);
  setText("collection-time", `Updated ${dateTimeFormat.format(new Date(metrics.generated_at))}`);
}

function renderLatestJoke() {
  const latest = metrics.latest_joke;
  setText("latest-date", dateFormat.format(new Date(latest.created_at)));
  const stage = document.getElementById("latest-post");
  stage.replaceChildren();

  const quote = document.createElement("blockquote");
  quote.className = "bluesky-embed post-fallback";
  quote.dataset.blueskyUri = latest.uri;

  const header = document.createElement("div");
  header.className = "post-fallback-header";
  const avatar = document.createElement("img");
  avatar.src = metrics.account.avatar;
  avatar.alt = "";
  const name = document.createElement("span");
  name.textContent = `${metrics.account.display_name} @${metrics.account.handle}`;
  header.append(avatar, name);

  const text = document.createElement("p");
  text.className = "post-fallback-text";
  text.textContent = latest.text;
  const link = document.createElement("a");
  link.href = latest.url;
  link.textContent = "View on Bluesky";
  quote.append(header, text, link);
  stage.append(quote);

  const script = document.createElement("script");
  script.src = EMBED_SCRIPT_URL;
  script.async = true;
  document.head.append(script);
}

function deltaText(current, previous) {
  if (!previous) return "Baseline snapshot";
  const difference = current - previous;
  if (difference === 0) return "No change";
  return `${difference > 0 ? "+" : ""}${numberFormat.format(difference)} since last update`;
}

function renderMetrics() {
  const current = metrics.current;
  const snapshots = metrics.snapshots;
  const previous = snapshots.length > 1 ? snapshots.at(-2) : null;
  setText("followers", compactFormat.format(current.followers));
  setText("following", compactFormat.format(current.following));
  setText("profile-posts", compactFormat.format(current.profile_posts));
  setText("engagement-rate", numberFormat.format(current.engagement_per_joke));
  setText("joke-posts", `Across ${numberFormat.format(current.joke_posts)} jokes`);
  setText("followers-delta", deltaText(current.followers, previous?.followers));
  setText("following-delta", deltaText(current.following, previous?.following));
  setText("posts-delta", deltaText(current.profile_posts, previous?.profile_posts));
}

function cutoffDate() {
  if (selectedRange === "all") return null;
  const cutoff = new Date(metrics.generated_at);
  cutoff.setUTCDate(cutoff.getUTCDate() - Number(selectedRange));
  return cutoff;
}

function inRange(value) {
  const cutoff = cutoffDate();
  return !cutoff || new Date(value) >= cutoff;
}

function replaceChart(name, context, config) {
  charts[name]?.destroy();
  charts[name] = new Chart(context, config);
}

function baseOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { intersect: false, mode: "index" },
    plugins: {
      legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8 } },
      tooltip: { displayColors: true },
    },
    scales: {
      x: { grid: { display: false }, ticks: { maxTicksLimit: 7 } },
      y: { beginAtZero: false, grid: { color: "#e4eaeb" } },
    },
  };
}

function renderAudienceChart() {
  const snapshots = metrics.snapshots.filter((item) => inRange(item.collected_at));
  const options = baseOptions();
  options.scales.yPosts = {
    position: "right",
    beginAtZero: false,
    grid: { drawOnChartArea: false },
  };
  replaceChart("audience", document.getElementById("audience-chart"), {
    type: "line",
    data: {
      labels: snapshots.map((item) => dateFormat.format(new Date(item.collected_at))),
      datasets: [
        {
          label: "Followers",
          data: snapshots.map((item) => item.followers),
          borderColor: colours[0],
          backgroundColor: colours[0],
          tension: 0.25,
        },
        {
          label: "Following",
          data: snapshots.map((item) => item.following),
          borderColor: colours[2],
          backgroundColor: colours[2],
          tension: 0.25,
        },
        {
          label: "Profile posts",
          data: snapshots.map((item) => item.profile_posts),
          borderColor: colours[3],
          backgroundColor: colours[3],
          tension: 0.25,
          yAxisID: "yPosts",
        },
      ],
    },
    options,
  });
  renderTable(
    "audience-table",
    snapshots.map((item) => [
      dateTimeFormat.format(new Date(item.collected_at)),
      metricText(item.followers),
      metricText(item.following),
      metricText(item.profile_posts),
    ]),
  );
}

function renderActivityChart() {
  const activity = metrics.daily_activity.filter((item) => inRange(`${item.date}T23:59:59Z`));
  const options = baseOptions();
  options.scales.y.beginAtZero = true;
  options.scales.y.ticks = { precision: 0 };
  replaceChart("activity", document.getElementById("activity-chart"), {
    type: "bar",
    data: {
      labels: activity.map((item) => dateFormat.format(new Date(`${item.date}T00:00:00Z`))),
      datasets: [
        { label: "Joke posts", data: activity.map((item) => item.joke_posts), backgroundColor: colours[0] },
        { label: "Follows", data: activity.map((item) => item.follows ?? 0), backgroundColor: colours[2] },
        { label: "Unfollows", data: activity.map((item) => item.unfollows), backgroundColor: colours[1] },
      ],
    },
    options,
  });
  renderTable(
    "activity-table",
    activity.map((item) => [item.date, item.joke_posts, item.follows ?? 0, item.unfollows]),
  );
}

function renderTable(id, rows) {
  const body = document.querySelector(`#${id} tbody`);
  body.replaceChildren();
  rows.forEach((row) => {
    const tableRow = document.createElement("tr");
    row.forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      tableRow.append(cell);
    });
    body.append(tableRow);
  });
}

function renderEngagement() {
  const entries = Object.entries(metrics.current.engagement);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  setText("engagement-total", numberFormat.format(total));
  replaceChart("engagement", document.getElementById("engagement-chart"), {
    type: "doughnut",
    data: {
      labels: entries.map(([name]) => name),
      datasets: [{ data: entries.map(([, count]) => count), backgroundColor: colours, borderWidth: 0 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "66%",
      plugins: { legend: { display: false } },
    },
  });
  const legend = document.getElementById("engagement-legend");
  legend.replaceChildren();
  entries.forEach(([name, count], index) => {
    const row = document.createElement("div");
    row.className = "legend-row";
    const swatch = document.createElement("span");
    swatch.className = "legend-swatch";
    swatch.style.background = colours[index];
    const label = document.createElement("span");
    label.textContent = name[0].toUpperCase() + name.slice(1);
    const value = document.createElement("strong");
    value.textContent = numberFormat.format(count);
    row.append(swatch, label, value);
    legend.append(row);
  });
}

function displayName(value) {
  const names = {
    api_ninjas: "API Ninjas",
    bluesky_dashboard: "Dashboard",
    bluesky_follow_fellows: "Follow fellows",
    bluesky_follows_and_likes: "Follows and likes",
    bluesky_manage_starter_pack: "Starter pack",
    bluesky_post_joke: "Post joke",
    bluesky_process_reports: "Process reports",
    bluesky_unfollow: "Unfollow",
    bluesky_validate_unfollow_ignore: "Validate unfollow ignore",
    codeql: "CodeQL",
    groandeck: "GroanDeck",
    icanhazdadjoke: "icanhazdadjoke",
    jokeapi: "JokeAPI",
    pr_auto_merge: "PR auto-merge",
    provider_health_check: "Provider health",
    python_tests: "Python tests",
    ruff_quality: "Ruff quality",
    syrsly: "Syrsly",
    validate_runtime_config: "Runtime config",
  };
  return names[value] || value.replaceAll("_", " ");
}

function appendCell(row, value, className) {
  const cell = document.createElement("td");
  if (className) cell.className = className;
  if (value instanceof Node) cell.append(value);
  else cell.textContent = value;
  row.append(cell);
}

function providerHealth(provider) {
  if (provider.configured === false) return { label: "Not configured", className: "unknown" };
  if (provider.healthy === true) return { label: "Healthy", className: "healthy" };
  if (provider.healthy === false) return { label: "Attention", className: "attention" };
  return { label: "No check", className: "unknown" };
}

function rejectionSummary(counts) {
  const labels = {
    duplicate: "duplicate",
    too_long: "too long",
    network_error: "network",
    provider_error: "provider",
  };
  const parts = Object.entries(counts || {})
    .filter(([, count]) => count > 0)
    .map(([reason, count]) => `${numberFormat.format(count)} ${labels[reason] || reason}`);
  return parts.length ? parts.join(" · ") : "--";
}

function renderProviders() {
  const providerMetrics = metrics.providers;
  const providers = providerMetrics.providers;
  const checked = providers.filter(
    (provider) => provider.configured !== false && provider.healthy !== null,
  );
  const healthy = checked.filter((provider) => provider.healthy === true).length;
  setText("providers-healthy", `${healthy}/${checked.length}`);
  setText("retained-publications", numberFormat.format(providerMetrics.retained_publications));

  const body = document.querySelector("#provider-table tbody");
  body.replaceChildren();
  providers.forEach((provider) => {
    const row = document.createElement("tr");
    const providerName = document.createElement("div");
    providerName.className = "provider-name";
    const name = document.createElement("strong");
    name.textContent = displayName(provider.name);
    const share = providerMetrics.retained_publications
      ? (provider.published * 100) / providerMetrics.retained_publications
      : 0;
    const bar = document.createElement("span");
    bar.className = "provider-share";
    bar.style.setProperty("--provider-share", `${share}%`);
    providerName.append(name, bar);
    if (provider.last_failure_reason) {
      const reason = document.createElement("small");
      reason.textContent = provider.last_failure_reason;
      providerName.append(reason);
    }
    appendCell(row, providerName);
    appendCell(row, numberFormat.format(provider.published));
    appendCell(
      row,
      provider.average_interactions === null
        ? "--"
        : numberFormat.format(provider.average_interactions),
    );
    appendCell(row, numberFormat.format(provider.fallthroughs));
    appendCell(row, rejectionSummary(provider.rejection_counts), "rejection-summary");
    const health = providerHealth(provider);
    const badge = document.createElement("span");
    badge.className = `health-badge ${health.className}`;
    badge.textContent = health.label;
    appendCell(row, badge);
    body.append(row);
  });
}

function renderAutomation() {
  const automation = metrics.automation;
  setText(
    "automation-rate",
    automation.success_rate === null ? "--" : `${numberFormat.format(automation.success_rate)}%`,
  );
  setText("automation-runs", numberFormat.format(automation.runs));
  setText("automation-failed", numberFormat.format(automation.failed));

  const body = document.querySelector("#workflow-table tbody");
  body.replaceChildren();
  [...automation.workflows]
    .sort((left, right) => right.runs - left.runs || left.name.localeCompare(right.name))
    .forEach((workflow) => {
      const row = document.createElement("tr");
      appendCell(row, displayName(workflow.name));
      appendCell(row, numberFormat.format(workflow.runs));
      const completed = workflow.successful + workflow.failed;
      appendCell(
        row,
        completed ? `${percentageFormat.format((workflow.successful * 100) / completed)}%` : "--",
      );
      appendCell(row, numberFormat.format(workflow.failed), workflow.failed ? "failure-count" : "");
      const latest = document.createElement("span");
      latest.className = `run-status ${workflow.last_conclusion || "unknown"}`;
      latest.textContent = workflow.last_conclusion || "No runs";
      appendCell(row, latest);
      body.append(row);
    });
}

function renderTopPosts() {
  const container = document.getElementById("top-posts");
  container.replaceChildren();
  metrics.top_posts.forEach((post) => {
    const article = document.createElement("article");
    article.className = "top-post";
    const text = document.createElement("p");
    text.className = "top-post-text";
    text.textContent = post.text;
    const footer = document.createElement("div");
    footer.className = "top-post-footer";
    const interactions = Object.values(post.engagement).reduce((sum, count) => sum + count, 0);
    const score = document.createElement("span");
    score.textContent = `${numberFormat.format(interactions)} interactions`;
    const link = document.createElement("a");
    link.href = post.url;
    link.textContent = "View post";
    footer.append(score, link);
    article.append(text, footer);
    container.append(article);
  });
}

function renderCharts() {
  renderAudienceChart();
  renderActivityChart();
  renderEngagement();
}

function bindRangeControls() {
  document.querySelectorAll("[data-range]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedRange = button.dataset.range;
      document.querySelectorAll("[data-range]").forEach((item) => {
        item.classList.toggle("active", item === button);
      });
      renderAudienceChart();
      renderActivityChart();
    });
  });
}

async function initialise() {
  try {
    const response = await fetch(DATA_URL);
    if (!response.ok) throw new Error(`Metrics request failed: ${response.status}`);
    metrics = await response.json();
    renderProfile();
    renderLatestJoke();
    renderMetrics();
    renderCharts();
    renderProviders();
    renderAutomation();
    renderTopPosts();
    bindRangeControls();
  } catch (error) {
    console.error(error);
    document.getElementById("page-error").hidden = false;
    setText("collection-time", "Statistics unavailable");
  }
}

initialise();
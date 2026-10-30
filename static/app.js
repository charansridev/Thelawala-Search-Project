// Thelawala Search - Safe DOM Client

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("search-form");
  const input = document.getElementById("search-input");
  const searchBtn = document.getElementById("search-btn");
  const clearBtn = document.getElementById("clear-btn");
  const validationMsg = document.getElementById("validation-msg");
  const loading = document.getElementById("loading");
  const errorBox = document.getElementById("error-box");
  const resultsSection = document.getElementById("results-section");
  const resultsList = document.getElementById("results-list");
  const resultsCount = document.getElementById("results-count");
  const noResults = document.getElementById("no-results");

  let abortController = null;

  // Toggle clear button visibility based on input
  input.addEventListener("input", () => {
    if (input.value.trim().length > 0) {
      clearBtn.style.display = "block";
    } else {
      clearBtn.style.display = "none";
    }
    // Clear validation error on typing
    hideValidation();
  });

  // Clear button resets the search interface
  clearBtn.addEventListener("click", () => {
    resetSearch();
    input.focus();
  });

  // Form submission (Enter key or Search button)
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const query = input.value.trim();

    if (!query) {
      showValidation("Please enter a product query to search.");
      input.focus();
      return;
    }

    performSearch(query);
  });

  function resetSearch() {
    input.value = "";
    clearBtn.style.display = "none";
    hideValidation();
    hideError();
    hideLoading();
    resultsSection.style.display = "none";
    resultsList.replaceChildren();
    noResults.style.display = "none";
    resultsCount.textContent = "";
    if (abortController) {
      abortController.abort();
      abortController = null;
    }
  }

  function showValidation(text) {
    validationMsg.textContent = text;
    validationMsg.style.display = "block";
  }

  function hideValidation() {
    validationMsg.textContent = "";
    validationMsg.style.display = "none";
  }

  function showError(text) {
    errorBox.textContent = text;
    errorBox.style.display = "block";
  }

  function hideError() {
    errorBox.textContent = "";
    errorBox.style.display = "none";
  }

  function showLoading() {
    loading.style.display = "flex";
    searchBtn.disabled = true;
    hideError();
    hideValidation();
  }

  function hideLoading() {
    loading.style.display = "none";
    searchBtn.disabled = false;
  }

  async function performSearch(query) {
    // Abort pending request if any
    if (abortController) {
      abortController.abort();
    }
    abortController = new AbortController();

    showLoading();
    resultsSection.style.display = "none";
    resultsList.replaceChildren();
    noResults.style.display = "none";

    try {
      const url = `/api/search?q=${encodeURIComponent(query)}&limit=10`;
      const response = await fetch(url, {
        signal: abortController.signal,
        headers: { "Accept": "application/json" },
      });

      if (!response.ok) {
        let errorDetail = "Failed to retrieve search results.";
        try {
          const errData = await response.json();
          if (errData && errData.detail) {
            errorDetail = errData.detail;
          }
        } catch {
          // ignore json parse error
        }
        showError(errorDetail);
        return;
      }

      const data = await response.json();
      renderResults(data.query, data.results || []);
    } catch (err) {
      if (err.name === "AbortError") {
        return;
      }
      showError("Connection error: Unable to reach the search server. Please check your network and try again.");
    } finally {
      hideLoading();
    }
  }

  function renderResults(query, results) {
    resultsSection.style.display = "block";
    resultsList.replaceChildren();

    if (results.length === 0) {
      resultsCount.textContent = "0 results";
      noResults.textContent = `No matching products found for "${query}".`;
      noResults.style.display = "block";
      return;
    }

    noResults.style.display = "none";
    resultsCount.textContent = `${results.length} result${results.length === 1 ? "" : "s"}`;

    results.forEach((sku, index) => {
      const li = document.createElement("li");
      li.className = "result-item";

      const mainDiv = document.createElement("div");
      mainDiv.className = "result-main";

      const numSpan = document.createElement("span");
      numSpan.className = "result-number";
      numSpan.textContent = `${index + 1}.`;

      const skuSpan = document.createElement("span");
      skuSpan.className = "result-sku";
      skuSpan.textContent = sku;

      mainDiv.appendChild(numSpan);
      mainDiv.appendChild(skuSpan);

      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "copy-btn";
      copyBtn.textContent = "Copy";
      copyBtn.title = `Copy SKU ${sku}`;
      copyBtn.setAttribute("aria-label", `Copy SKU ${sku}`);

      copyBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(sku);
          copyBtn.textContent = "Copied!";
          copyBtn.classList.add("copied");
          setTimeout(() => {
            copyBtn.textContent = "Copy";
            copyBtn.classList.remove("copied");
          }, 1500);
        } catch {
          copyBtn.textContent = "Failed";
          setTimeout(() => {
            copyBtn.textContent = "Copy";
          }, 1500);
        }
      });

      li.appendChild(mainDiv);
      li.appendChild(copyBtn);
      resultsList.appendChild(li);
    });
  }
});

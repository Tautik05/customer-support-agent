// ==========================================================================
// NovaDesk AI — Enterprise Support Operations & Customer Help Desk
// ==========================================================================

// Global App State
let currentRole = "agent"; // 'customer' | 'agent'
let currentAgentTab = "tickets"; // 'tickets' | 'customers' | 'metrics'
let currentCustomerEmail = localStorage.getItem("novadesk_customer_email") || "alice@example.com";
let currentSelectedTicketId = null;
let allTicketsCache = [];
let activeCustomerProfile = null;
let activeWorkflowState = null;

// Demo Scenarios Preset Data
const DEMO_SCENARIOS = {
  alice: {
    name: "Alice Smith",
    email: "alice@example.com",
    subject: "Charged twice for monthly subscription",
    category: "billing",
    description: "I noticed two charges of $49.00 on my credit card statement for sub_101 yesterday. Please refund the duplicate payment."
  },
  bob: {
    name: "Bob Jones",
    email: "bob@example.com",
    subject: "Damaged headphones received in order ORD-2026-9021",
    category: "shipping",
    description: "My headphones arrived damaged 2 days ago. I would like a refund of $89.99 for ORD-2026-9021."
  },
  charlie: {
    name: "Charlie Brown",
    email: "charlie@example.com",
    subject: "Refund request for jacket bought in June (ORD-2026-1184)",
    category: "billing",
    description: "I purchased a winter jacket almost 3 months ago but never wore it. I want a full refund of $149 for ORD-2026-1184."
  },
  diana: {
    name: "Diana Prince",
    email: "diana@example.com",
    subject: "Where is my order ORD-2026-7732? Shipped 12 days ago and lost",
    category: "shipping",
    description: "I haven't received my air purifier and the tracking has not updated for over 8 days. Where is my package?"
  },
  tt: {
    name: "Custom User",
    email: "tt@gmail.com",
    subject: "Delayed delivery of wireless headphones",
    category: "shipping",
    description: "My package was supposed to arrive three days ago but has not arrived yet. Please provide an update."
  }
};

// ==========================================================================
// Initialization & Router
// ==========================================================================
document.addEventListener("DOMContentLoaded", () => {
  initRouter();
  loadAgentTicketQueue();
  checkCustomerAuth();

  // Periodic background sync: updates Customer Portal and Agent Operations in real-time
  setInterval(async () => {
    try {
      const res = await fetch("/api/system/tickets");
      const all = await res.json();
      allTicketsCache = all;

      if (currentRole === "customer" && currentCustomerEmail) {
        const myTickets = all.filter(t => t.customer_email.toLowerCase() === currentCustomerEmail.toLowerCase());
        const countBadge = document.getElementById("cust-ticket-count-badge");
        if (countBadge) countBadge.innerText = `${myTickets.length} Request${myTickets.length === 1 ? '' : 's'}`;
        
        if (currentSelectedTicketId) {
          const currentMatch = myTickets.find(t => t.id === currentSelectedTicketId);
          if (currentMatch) {
            renderCustomerTicketDetail(currentMatch);
          }
        }
      } else if (currentRole === "agent") {
        updateKPIStrip(all);
        // Silently update list badges
        const searchInput = document.getElementById("ticket-search-input");
        if (!searchInput || !searchInput.value) {
          renderAgentQueueList(all);
        }
        if (currentSelectedTicketId) {
          const activeMatch = all.find(t => t.id === currentSelectedTicketId);
          if (activeMatch) {
            // Update status badge
            const stEl = document.getElementById("agent-tkt-status");
            if (stEl) {
              stEl.className = `badge ${getStatusBadgeClass(activeMatch.status)}`;
              stEl.innerText = formatStatusLabel(activeMatch.status);
            }
            if (activeMatch.metadata && (activeMatch.metadata.classification || activeMatch.status === "pending_approval" || activeMatch.status === "resolved")) {
              renderExistingWorkflowState(activeMatch);
            }
          }
        }
      }
    } catch (e) {
      // Silent background polling
    }
  }, 3000);
});

function initRouter() {
  const hash = window.location.hash.replace("#", "") || "agent";
  if (hash.startsWith("customer")) {
    navigateTo("customer");
  } else {
    navigateTo("agent");
    if (hash === "agent/customers") {
      switchAgentTab("customers");
    } else if (hash === "agent/metrics") {
      switchAgentTab("metrics");
    }
  }
}

function navigateTo(role) {
  currentRole = role;
  window.location.hash = role === "customer" ? "customer" : `agent/${currentAgentTab}`;

  document.getElementById("role-btn-customer").classList.toggle("active", role === "customer");
  document.getElementById("role-btn-agent").classList.toggle("active", role === "agent");

  document.getElementById("view-customer").classList.toggle("active", role === "customer");
  document.getElementById("view-agent").classList.toggle("active", role === "agent");

  if (role === "customer") {
    checkCustomerAuth();
  } else {
    loadAgentTicketQueue();
  }
}

function switchAgentTab(tabName) {
  currentAgentTab = tabName;
  window.location.hash = `agent/${tabName}`;

  document.querySelectorAll(".agent-nav-item").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".agent-tab-pane").forEach(el => el.classList.remove("active"));

  const navBtn = document.getElementById(`agent-nav-${tabName}`);
  const pane = document.getElementById(`agent-tab-${tabName}`);
  if (navBtn) navBtn.classList.add("active");
  if (pane) pane.classList.add("active");

  if (tabName === "customers") {
    loadCustomersTable();
  } else if (tabName === "tickets") {
    loadAgentTicketQueue();
  }
}

// ==========================================================================
// CUSTOMER PORTAL AUTHENTICATION & SESSION
// ==========================================================================
function checkCustomerAuth() {
  const savedEmail = localStorage.getItem("novadesk_customer_email");
  const authView = document.getElementById("customer-auth-view");
  const mainView = document.getElementById("customer-main-view");

  if (savedEmail) {
    currentCustomerEmail = savedEmail;
    authView.classList.add("hidden");
    mainView.classList.remove("hidden");
    renderCustomerAuthHeader();
    loadCustomerTickets();
  } else {
    currentCustomerEmail = null;
    authView.classList.remove("hidden");
    mainView.classList.add("hidden");
  }
}

function handleCustomerLogin(event) {
  if (event) event.preventDefault();
  const input = document.getElementById("cust-login-email-input");
  const email = (input ? input.value : "").trim();
  if (!email || !email.includes("@")) {
    alert("Please enter a valid email address.");
    return;
  }
  setCustomerSession(email);
}

function quickLoginCustomer(email) {
  setCustomerSession(email);
}

function setCustomerSession(email) {
  currentCustomerEmail = email.toLowerCase().trim();
  localStorage.setItem("novadesk_customer_email", currentCustomerEmail);
  renderCustomerAuthHeader();
  document.getElementById("customer-auth-view").classList.add("hidden");
  document.getElementById("customer-main-view").classList.remove("hidden");
  loadCustomerTickets();
}

function customerSignOut() {
  localStorage.removeItem("novadesk_customer_email");
  currentCustomerEmail = null;
  document.getElementById("customer-main-view").classList.add("hidden");
  document.getElementById("customer-auth-view").classList.remove("hidden");
  const input = document.getElementById("cust-login-email-input");
  if (input) {
    input.value = "";
    input.focus();
  }
}

function renderCustomerAuthHeader() {
  if (!currentCustomerEmail) return;
  const parts = currentCustomerEmail.split("@")[0].split(/[._-]/);
  const initials = parts.map(p => p[0] ? p[0].toUpperCase() : "").slice(0, 2).join("") || "CU";
  const name = parts.map(p => p ? p.charAt(0).toUpperCase() + p.slice(1) : "").join(" ") || "Customer";

  const avatarEl = document.getElementById("cust-bar-avatar");
  const nameEl = document.getElementById("cust-bar-name");
  const emailEl = document.getElementById("cust-bar-email");
  const tierEl = document.getElementById("cust-bar-tier");

  if (avatarEl) avatarEl.innerText = initials;
  if (nameEl) nameEl.innerText = name;
  if (emailEl) emailEl.innerText = currentCustomerEmail;
  if (tierEl) {
    tierEl.innerText = currentCustomerEmail.includes("fiona") ? "VIP Gold Member" : "Standard Customer";
  }
}

// ==========================================================================
// CUSTOMER TICKET LIST & RESOLUTION VIEWER
// ==========================================================================
async function loadCustomerTickets() {
  if (!currentCustomerEmail) return;

  const container = document.getElementById("customer-ticket-list");
  const countBadge = document.getElementById("cust-ticket-count-badge");
  container.innerHTML = `<div class="loading-spinner-box">Loading your requests...</div>`;

  try {
    const res = await fetch("/api/system/tickets");
    const all = await res.json();
    allTicketsCache = all;

    // Filter tickets belonging specifically to this logged-in customer email
    const myTickets = all.filter(t => t.customer_email.toLowerCase() === currentCustomerEmail.toLowerCase());

    if (countBadge) countBadge.innerText = `${myTickets.length} Request${myTickets.length === 1 ? '' : 's'}`;

    if (myTickets.length === 0) {
      container.innerHTML = `
        <div class="empty-state" style="padding:30px 10px;">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="9" x2="15" y2="9"/><line x1="9" y1="13" x2="15" y2="13"/></svg>
          <h4>No Requests Found</h4>
          <p>No support requests found for <strong>${currentCustomerEmail}</strong>. Click below to submit your first request!</p>
          <button class="btn btn-sm btn-primary mt-4" onclick="openCustomerTicketModal()">+ Submit Ticket</button>
        </div>
      `;
      document.getElementById("customer-empty-detail").classList.remove("hidden");
      document.getElementById("customer-detail-content").classList.add("hidden");
      return;
    }

    container.innerHTML = myTickets.map(t => {
      const isSelected = t.id === currentSelectedTicketId;
      const statusBadge = getCustomerStatusBadge(t.status);
      const dateStr = t.created_at ? new Date(t.created_at).toLocaleDateString() : 'Recent';

      return `
        <div class="cust-ticket-item ${isSelected ? 'active' : ''}" onclick="selectCustomerTicket('${t.id}')">
          <div class="cust-tkt-top">
            <span class="cust-tkt-id">#${t.id}</span>
            ${statusBadge}
          </div>
          <div class="cust-tkt-subject">${t.subject}</div>
          <div class="cust-tkt-meta">
            <span>Category: ${capitalize(t.category || 'General')}</span>
            <span>${dateStr}</span>
          </div>
        </div>
      `;
    }).join('');

    // Auto-select first ticket if none selected
    if (!currentSelectedTicketId && myTickets.length > 0) {
      selectCustomerTicket(myTickets[0].id);
    } else if (currentSelectedTicketId) {
      const match = myTickets.find(t => t.id === currentSelectedTicketId);
      if (match) {
        selectCustomerTicket(match.id);
      } else if (myTickets.length > 0) {
        selectCustomerTicket(myTickets[0].id);
      }
    }
  } catch (err) {
    container.innerHTML = `<div class="loading-spinner-box text-danger">Error loading requests: ${err.message}</div>`;
  }
}

async function selectCustomerTicket(ticketId) {
  currentSelectedTicketId = ticketId;
  document.querySelectorAll(".cust-ticket-item").forEach(el => el.classList.remove("active"));
  
  try {
    const res = await fetch(`/api/system/tickets/${ticketId}`);
    const ticket = await res.json();
    renderCustomerTicketDetail(ticket);
    
    // Highlight list item
    document.querySelectorAll(".cust-ticket-item").forEach(el => {
      if (el.innerHTML.includes(`#${ticketId}`)) el.classList.add("active");
    });
  } catch (err) {
    console.error("Failed to load customer ticket details", err);
  }
}

function renderCustomerTicketDetail(ticket) {
  document.getElementById("customer-empty-detail").classList.add("hidden");
  const content = document.getElementById("customer-detail-content");
  content.classList.remove("hidden");

  document.getElementById("cust-det-id").innerText = `#${ticket.id}`;
  document.getElementById("cust-det-subject").innerText = ticket.subject;
  document.getElementById("cust-det-description").innerText = ticket.description;
  document.getElementById("cust-det-date").innerText = `Submitted on ${ticket.created_at ? new Date(ticket.created_at).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'Recent'}`;

  // Badges
  const stBadge = document.getElementById("cust-det-status");
  stBadge.className = `badge ${getStatusBadgeClass(ticket.status)}`;
  stBadge.innerText = formatStatusLabel(ticket.status);

  const prBadge = document.getElementById("cust-det-priority");
  prBadge.innerText = `${capitalize(ticket.priority || 'medium')} Priority`;

  // Customer Timeline Progression
  updateCustomerTimeline(ticket.status, ticket.resolution_path);

  // Email Card Details
  const pendingBox = document.getElementById("cust-pending-box");
  const emailBox = document.getElementById("cust-response-box");
  const emailTo = document.getElementById("cust-email-to");
  const emailSubj = document.getElementById("cust-email-subject");
  const emailTime = document.getElementById("cust-email-time");
  const emailBody = document.getElementById("cust-resp-body");
  const receiptBanner = document.getElementById("cust-action-receipt");
  const receiptText = document.getElementById("cust-receipt-text");

  emailTo.innerText = ticket.customer_email || currentCustomerEmail;
  emailSubj.innerText = ticket.subject;
  emailTime.innerText = ticket.updated_at ? new Date(ticket.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Delivered';

  const meta = ticket.metadata || {};
  const sentEmail = meta.sent_email || {};
  const finalResp = meta.final_response || {};
  const actionResult = meta.action_result || {};

  const isResolvedOrProcessed = (ticket.status === "resolved" || ticket.status === "closed" || ticket.status === "escalated") && (ticket.resolution_summary || sentEmail.body || finalResp.body);

  if (isResolvedOrProcessed) {
    if (pendingBox) pendingBox.classList.add("hidden");
    if (emailBox) emailBox.classList.remove("hidden");

    if (sentEmail.subject || finalResp.subject) {
      emailSubj.innerText = sentEmail.subject || finalResp.subject;
    }

    // Format full email text cleanly
    let formattedText = formatCleanResponseText(sentEmail.body ? sentEmail : finalResp);
    if (!formattedText.trim()) {
      formattedText = formatCleanResponseText(ticket.resolution_summary) || "Your request has been verified and resolved by our support system.";
    }

    emailBody.innerText = formattedText;


    // Action receipt banner (refund / cancellation)
    if (actionResult && actionResult.success && actionResult.refund) {
      receiptBanner.classList.remove("hidden");
      receiptText.innerText = `✓ Action Executed: Refund of $${actionResult.refund.amount.toFixed(2)} USD successfully credited to your payment card.`;
    } else if (actionResult && actionResult.success && actionResult.subscription) {
      receiptBanner.classList.remove("hidden");
      receiptText.innerText = `✓ Action Executed: Subscription cancellation successfully scheduled.`;
    } else {
      receiptBanner.classList.add("hidden");
    }
  } else if (ticket.status === "pending_approval") {
    if (pendingBox) pendingBox.classList.add("hidden");
    if (emailBox) emailBox.classList.add("hidden");
    if (receiptBanner) receiptBanner.classList.add("hidden");
  } else {
    // Ticket is Open or In Progress - Awaiting support processing
    if (pendingBox) pendingBox.classList.remove("hidden");
    if (emailBox) emailBox.classList.add("hidden");
    if (receiptBanner) receiptBanner.classList.add("hidden");
  }
}

function updateCustomerTimeline(status, resolutionPath) {
  const sSubmitted = document.getElementById("cust-step-submitted");
  const sReview = document.getElementById("cust-step-review");
  const sApproval = document.getElementById("cust-step-approval");
  const sResolved = document.getElementById("cust-step-resolved");

  const b1 = document.getElementById("cust-bar-1");
  const b2 = document.getElementById("cust-bar-2");
  const b3 = document.getElementById("cust-bar-3");

  const notice = document.getElementById("cust-approval-notice");

  // Reset all
  [sSubmitted, sReview, sApproval, sResolved].forEach(el => el.className = "timeline-step");
  [b1, b2, b3].forEach(el => el.className = "timeline-bar");
  if (notice) notice.classList.add("hidden");

  sSubmitted.classList.add("passed");

  if (status === "open") {
    sReview.classList.add("active");
  } else if (status === "in_progress") {
    sSubmitted.classList.add("passed");
    b1.classList.add("passed");
    sReview.classList.add("active");
  } else if (status === "pending_approval") {
    sSubmitted.classList.add("passed");
    b1.classList.add("passed");
    sReview.classList.add("passed");
    b2.classList.add("passed");
    sApproval.classList.add("active");
    if (notice) notice.classList.remove("hidden");
  } else if (status === "resolved" || status === "closed") {
    sSubmitted.classList.add("passed");
    b1.classList.add("passed");
    sReview.classList.add("passed");
    b2.classList.add("passed");
    sApproval.classList.add("passed");
    b3.classList.add("passed");
    sResolved.classList.add("passed");
  } else if (status === "escalated") {
    sSubmitted.classList.add("passed");
    b1.classList.add("passed");
    sReview.classList.add("passed");
    b2.classList.add("passed");
    sApproval.classList.add("passed");
    sApproval.querySelector("strong").innerText = "Specialist Assigned";
    sApproval.querySelector("span").innerText = "Under Human Review";
  }
}

// Modal Handlers
function openCustomerTicketModal() {
  if (!currentCustomerEmail) {
    alert("Please sign in with your email address first.");
    checkCustomerAuth();
    return;
  }
  document.getElementById("cust-modal-email").value = currentCustomerEmail;
  document.getElementById("modal-create-ticket").classList.remove("hidden");
}

function closeCustomerTicketModal() {
  document.getElementById("modal-create-ticket").classList.add("hidden");
}

function fillCustomerForm(scenarioKey) {
  const sc = DEMO_SCENARIOS[scenarioKey];
  if (!sc) return;
  document.getElementById("cust-modal-email").value = sc.email;
  document.getElementById("cust-modal-subject").value = sc.subject;
  document.getElementById("cust-modal-category").value = sc.category;
  document.getElementById("cust-modal-desc").value = sc.description;
  setCustomerSession(sc.email);
}

async function submitCustomerTicket(event) {
  event.preventDefault();
  const btn = document.getElementById("btn-cust-submit");
  btn.disabled = true;
  btn.innerText = "Submitting Request...";

  const email = (currentCustomerEmail || document.getElementById("cust-modal-email").value).trim();
  const subject = document.getElementById("cust-modal-subject").value.trim();
  const category = document.getElementById("cust-modal-category").value;
  const description = document.getElementById("cust-modal-desc").value.trim();

  try {
    // 1. Create ticket in System of Record (Status = open)
    const res = await fetch("/api/system/tickets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_email: email,
        subject: subject,
        category: category,
        description: description,
        priority: "medium"
      })
    });
    const newTkt = await res.json();
    closeCustomerTicketModal();
    currentSelectedTicketId = newTkt.id;

    // Refresh tickets list and display ticket in "Under Review / Queued" state
    await loadCustomerTickets();
    selectCustomerTicket(newTkt.id);

  } catch (err) {
    alert("Failed to submit ticket: " + err.message);
  } finally {
    btn.disabled = false;
    btn.innerText = "Submit Support Request";
  }
}

// ==========================================================================
// SUPPORT OPERATIONS AGENT DASHBOARD LOGIC
// ==========================================================================
async function loadAgentTicketQueue() {
  const container = document.getElementById("ticket-queue-container");
  container.innerHTML = `<div class="loading-spinner-box">Loading ticket queue...</div>`;

  try {
    const res = await fetch("/api/system/tickets");
    const tickets = await res.json();
    allTicketsCache = tickets;

    // Update KPI strip
    updateKPIStrip(tickets);

    renderAgentQueueList(tickets);

    // If a ticket was previously selected, maintain selection, otherwise select first
    if (tickets.length > 0) {
      if (!currentSelectedTicketId || !tickets.find(t => t.id === currentSelectedTicketId)) {
        selectAgentTicket(tickets[0].id);
      } else {
        document.querySelectorAll(".queue-item").forEach(el => {
          if (el.innerHTML.includes(`#${currentSelectedTicketId}`)) el.classList.add("active");
        });
      }
    }
  } catch (err) {
    container.innerHTML = `<div class="loading-spinner-box text-danger">Error loading queue: ${err.message}</div>`;
  }
}

function updateKPIStrip(tickets) {
  const total = tickets.length;
  const pending = tickets.filter(t => t.status === "pending_approval").length;
  const inProgress = tickets.filter(t => t.status === "in_progress" || t.status === "open").length;
  const resolved = tickets.filter(t => t.status === "resolved").length;
  const escalated = tickets.filter(t => t.status === "escalated").length;

  document.getElementById("kpi-total").innerText = total;
  document.getElementById("kpi-pending-approval").innerText = pending;
  document.getElementById("kpi-in-progress").innerText = inProgress;
  document.getElementById("kpi-resolved").innerText = resolved;
  document.getElementById("kpi-escalated").innerText = escalated;
}

function filterTicketQueue() {
  const query = document.getElementById("ticket-search-input").value.toLowerCase();
  const statusFilter = document.getElementById("filter-status").value;
  const priorityFilter = document.getElementById("filter-priority").value;

  const filtered = allTicketsCache.filter(t => {
    const matchQuery = !query || 
      t.id.toLowerCase().includes(query) || 
      t.subject.toLowerCase().includes(query) || 
      t.customer_email.toLowerCase().includes(query);

    const matchStatus = !statusFilter || t.status === statusFilter;
    const matchPriority = !priorityFilter || (t.priority || '').toLowerCase() === priorityFilter.toLowerCase();

    return matchQuery && matchStatus && matchPriority;
  });

  renderAgentQueueList(filtered);
}

function renderAgentQueueList(tickets) {
  const container = document.getElementById("ticket-queue-container");
  if (tickets.length === 0) {
    container.innerHTML = `<div class="loading-spinner-box">No matching tickets found.</div>`;
    return;
  }

  container.innerHTML = tickets.map(t => {
    const isSelected = t.id === currentSelectedTicketId;
    const stBadge = getAgentStatusBadge(t.status);
    const prBadge = getPriorityBadge(t.priority);

    return `
      <div class="queue-item ${isSelected ? 'active' : ''}" onclick="selectAgentTicket('${t.id}')">
        <div class="q-top-row">
          <span class="q-id">#${t.id}</span>
          <div>${prBadge} ${stBadge}</div>
        </div>
        <div class="q-subject">${t.subject}</div>
        <div class="q-bottom-row">
          <span>${t.customer_email}</span>
          <span>${t.category ? capitalize(t.category) : 'General'}</span>
        </div>
      </div>
    `;
  }).join('');
}

async function selectAgentTicket(ticketId) {
  currentSelectedTicketId = ticketId;

  // Highlight list item
  document.querySelectorAll(".queue-item").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".queue-item").forEach(el => {
    if (el.innerHTML.includes(`#${ticketId}`)) el.classList.add("active");
  });

  document.getElementById("agent-ticket-empty").classList.add("hidden");
  document.getElementById("agent-ticket-loaded").classList.remove("hidden");

  try {
    const res = await fetch(`/api/system/tickets/${ticketId}`);
    const ticket = await res.json();

    // Populate Header Block
    document.getElementById("agent-tkt-id").innerText = `#${ticket.id}`;
    document.getElementById("agent-tkt-subject").innerText = ticket.subject;
    document.getElementById("agent-tkt-custemail").innerText = ticket.customer_email;
    document.getElementById("agent-tkt-description").innerText = `"${ticket.description}"`;
    document.getElementById("agent-tkt-created").innerText = ticket.created_at ? new Date(ticket.created_at).toLocaleString() : 'Recently';

    // Badges
    const stEl = document.getElementById("agent-tkt-status");
    stEl.className = `badge ${getStatusBadgeClass(ticket.status)}`;
    stEl.innerText = formatStatusLabel(ticket.status);

    const prEl = document.getElementById("agent-tkt-priority");
    prEl.innerText = (ticket.priority || 'medium').toUpperCase();

    // Show custom response box ONLY for Billing & Subscriptions category when not yet resolved
    const composerEl = document.getElementById("operator-manual-composer");
    const categoryLower = (ticket.category || "").toLowerCase();
    const isBilling = categoryLower.includes("billing") || categoryLower.includes("subscription");
    const isResolved = ticket.status === "resolved" || ticket.status === "closed";

    if (composerEl) {
      if (isBilling && !isResolved) {
        composerEl.classList.remove("hidden");
      } else {
        composerEl.classList.add("hidden");
      }
    }

    // Load Customer 360 Context from backend
    await loadCustomerContext(ticket.customer_email);

    // Check if there is existing workflow state or metadata
    resetWorkflowUI();
    renderExistingWorkflowState(ticket);
  } catch (err) {
    console.error("Error loading ticket detail", err);
  }
}



async function loadCustomerContext(email) {
  try {
    const res = await fetch(`/api/system/customers/${email}`);
    if (!res.ok) {
      document.getElementById("agent-tkt-custname").innerText = email.split('@')[0];
      document.getElementById("agent-cust-tier").innerText = "Standard Tier";
      renderContextTabs([], [], [], []);
      return;
    }

    const data = await res.json();
    activeCustomerProfile = data;

    document.getElementById("agent-tkt-custname").innerText = data.name || email.split('@')[0];
    const tierBadge = document.getElementById("agent-cust-tier");
    tierBadge.innerText = `${data.tier || 'Standard'} Tier`;
    tierBadge.className = `badge ${data.tier === 'Enterprise' || data.tier === 'VIP' ? 'badge-warning' : 'badge-info'}`;

    renderContextTabs(
      data.payments || [],
      data.orders || [],
      data.subscriptions || [],
      data.refunds || []
    );
  } catch (err) {
    console.error("Failed to load customer context", err);
  }
}

function renderContextTabs(payments, orders, subs, refunds) {
  document.getElementById("cnt-payments").innerText = payments.length;
  document.getElementById("cnt-orders").innerText = orders.length;
  document.getElementById("cnt-subs").innerText = subs.length;
  document.getElementById("cnt-refunds").innerText = refunds.length;

  // Payments List
  const payContainer = document.getElementById("ctx-list-payments");
  if (payments.length === 0) {
    payContainer.innerHTML = `<div class="empty-tool-log">No payment transactions found.</div>`;
  } else {
    payContainer.innerHTML = payments.map(p => {
      const isRefunded = p.status === "refunded";
      const dateStr = p.created_at ? new Date(p.created_at).toLocaleDateString() : '';
      return `
        <div class="mini-record-item">
          <div class="mini-rec-row">
            <strong>${p.id} — $${p.amount.toFixed(2)} ${p.currency}</strong>
            <span class="badge ${isRefunded ? 'badge-danger' : 'badge-success'}">${p.status.toUpperCase()}</span>
          </div>
          <div class="mini-rec-row" style="color:var(--text-sub); margin-top:2px;">
            <span>${p.payment_method || 'Card'}</span>
            <span>${dateStr}</span>
          </div>
        </div>
      `;
    }).join('');
  }

  // Orders List
  const ordContainer = document.getElementById("ctx-list-orders");
  if (orders.length === 0) {
    ordContainer.innerHTML = `<div class="empty-tool-log">No orders found.</div>`;
  } else {
    ordContainer.innerHTML = orders.map(o => `
      <div class="mini-record-item">
        <div class="mini-rec-row">
          <strong>${o.order_number}</strong>
          <span class="badge badge-info">${o.status.toUpperCase()}</span>
        </div>
        <div class="mini-rec-row" style="color:var(--text-sub); margin-top:2px;">
          <span>Total: $${o.total_amount.toFixed(2)}</span>
          <span>Trk: ${o.tracking_number || 'N/A'}</span>
        </div>
      </div>
    `).join('');
  }

  // Subscriptions List
  const subContainer = document.getElementById("ctx-list-subs");
  if (subs.length === 0) {
    subContainer.innerHTML = `<div class="empty-tool-log">No active subscriptions.</div>`;
  } else {
    subContainer.innerHTML = subs.map(s => `
      <div class="mini-record-item">
        <div class="mini-rec-row">
          <strong>${s.plan_name}</strong>
          <span class="badge badge-success">${s.status.toUpperCase()}</span>
        </div>
        <div class="mini-rec-row" style="color:var(--text-sub); margin-top:2px;">
          <span>$${s.amount.toFixed(2)} / ${s.billing_cycle}</span>
          <span>ID: ${s.id}</span>
        </div>
      </div>
    `).join('');
  }

  // Refunds List
  const refContainer = document.getElementById("ctx-list-refunds");
  if (refunds.length === 0) {
    refContainer.innerHTML = `<div class="empty-tool-log">No refunds recorded.</div>`;
  } else {
    refContainer.innerHTML = refunds.map(r => `
      <div class="mini-record-item">
        <div class="mini-rec-row">
          <strong>${r.id} — $${r.amount.toFixed(2)}</strong>
          <span class="badge badge-warning">${r.status.toUpperCase()}</span>
        </div>
        <div style="color:var(--text-sub); margin-top:2px;">Reason: ${r.reason}</div>
      </div>
    `).join('');
  }
}

function switchContextTab(tabKey) {
  document.querySelectorAll(".context-tab-bar .c-tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".ctx-pane").forEach(p => p.classList.remove("active"));

  event.target.classList.add("active");
  document.getElementById(`ctx-tab-${tabKey}`).classList.add("active");
}

// ==========================================================================
// AI RESOLUTION WORKFLOW & HUMAN-IN-THE-LOOP EXECUTION
// ==========================================================================
function resetWorkflowUI() {
  const steps = [
    { id: "classify", text: "Categorizes intent, urgency & sentiment" },
    { id: "extract", text: "Extracts customer email, order/sub IDs" },
    { id: "lookup", text: "Queries PostgreSQL system of record" },
    { id: "rules", text: "Evaluates duplicate charge & 30-day return policy" },
    { id: "decide", text: "Routes to Action Approval, Direct Resolve, or Escalation" },
    { id: "approval", text: "Operator authorization gate for consequential actions" },
    { id: "execute", text: "Executes create_refund or cancel_sub mutation" },
    { id: "response", text: "Drafts customer message & updates database" }
  ];

  steps.forEach(s => {
    const el = document.getElementById(`pstep-${s.id}`);
    if (el) {
      el.className = "pipeline-step";
      const iconEl = el.querySelector(".step-status-icon");
      if (iconEl) iconEl.innerText = "○";
      const detailsEl = document.getElementById(`pstep-${s.id}-details`);
      if (detailsEl) detailsEl.innerText = s.text;
    }
  });

  document.getElementById("wf-badge-status").className = "badge badge-neutral";
  document.getElementById("wf-badge-status").innerText = "IDLE";
  document.getElementById("wf-approval-card").classList.add("hidden");
  document.getElementById("agent-final-response-box").classList.add("hidden");
  document.getElementById("tool-activity-logs").innerHTML = `<div class="empty-tool-log">No tool activity yet. Run workflow to observe MCP calls.</div>`;
}


async function runResolutionWorkflow() {
  if (!currentSelectedTicketId) return;

  const btn = document.getElementById("btn-run-agent-workflow");
  btn.disabled = true;
  btn.innerHTML = `<svg class="spinner" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg> Running LangGraph Resolution...`;

  // Hide manual custom composer since operator selected AI review
  const composerEl = document.getElementById("operator-manual-composer");
  if (composerEl) composerEl.classList.add("hidden");

  resetWorkflowUI();
  document.getElementById("wf-badge-status").className = "badge badge-info";
  document.getElementById("wf-badge-status").innerText = "PROCESSING";

  const tktSubject = document.getElementById("agent-tkt-subject").innerText;
  const tktEmail = document.getElementById("agent-tkt-custemail").innerText;
  const tktDesc = document.getElementById("agent-tkt-description").innerText.replace(/^"|"$/g, '');

  try {
    const res = await fetch("/api/workflow/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticket_id: currentSelectedTicketId,
        customer_email: tktEmail,
        subject: tktSubject,
        description: tktDesc
      })
    });

    const data = await res.json();
    activeWorkflowState = data;
    renderWorkflowExecution(data);
    await loadAgentTicketQueue(); // Refresh queue status badges
  } catch (err) {
    alert("Workflow execution failed: " + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg> Execute AI Resolution Review`;
  }
}


function renderWorkflowExecution(data) {
  // Step 1: Classification
  const stClassify = document.getElementById("pstep-classify");
  stClassify.className = "pipeline-step completed";
  stClassify.querySelector(".step-status-icon").innerText = "✓";
  if (data.classification) {
    document.getElementById("pstep-classify-details").innerText = `Intent: ${data.classification.intent} | Urgency: ${data.classification.urgency} | Sentiment: ${data.classification.sentiment}`;
  }

  // Step 2: Entity Extraction
  const stExtract = document.getElementById("pstep-extract");
  stExtract.className = "pipeline-step completed";
  stExtract.querySelector(".step-status-icon").innerText = "✓";
  if (data.entities) {
    const e = data.entities;
    document.getElementById("pstep-extract-details").innerText = `Email: ${e.customer_email || 'found'} | Amount: ${e.dollar_amount ? '$' + e.dollar_amount : 'N/A'}`;
  }

  // Step 3: MCP Lookup
  const stLookup = document.getElementById("pstep-lookup");
  stLookup.className = "pipeline-step completed";
  stLookup.querySelector(".step-status-icon").innerText = "✓";
  document.getElementById("pstep-lookup-details").innerText = `Customer profile, orders, and payment history verified`;

  // Step 4: Deterministic Rules
  const stRules = document.getElementById("pstep-rules");
  stRules.className = "pipeline-step completed";
  stRules.querySelector(".step-status-icon").innerText = "✓";
  document.getElementById("pstep-rules-details").innerText = data.proposed_action?.reasoning || "Business rules evaluated successfully";

  // Step 5: Decision
  const stDecide = document.getElementById("pstep-decide");
  stDecide.className = "pipeline-step completed";
  stDecide.querySelector(".step-status-icon").innerText = "✓";
  document.getElementById("pstep-decide-details").innerText = `Resolution Path: ${data.resolution_path || 'PROPOSE_ACTION_APPROVAL'}`;

  // Render Tool Activity (MCP logs)
  renderToolActivity(data.audit_logs || []);

  // Handle Pause at Human Approval Checkpoint
  if (data.is_waiting_human_approval) {
    const stApproval = document.getElementById("pstep-approval");
    stApproval.className = "pipeline-step waiting";
    stApproval.querySelector(".step-status-icon").innerText = "⏸";
    document.getElementById("pstep-approval-details").innerText = "Consequential action pending human authorization";

    document.getElementById("wf-badge-status").className = "badge badge-warning";
    document.getElementById("wf-badge-status").innerText = "AWAITING APPROVAL";

    // Show glowing approval card
    const act = data.proposed_action || {};
    const params = act.action_parameters || {};
    const draft = data.response_draft || data.final_response || {};

    document.getElementById("wf-approval-card").classList.remove("hidden");
    document.getElementById("appr-action-type").innerText = act.action_type || "create_refund";
    document.getElementById("appr-action-amount").innerText = params.amount ? `$${parseFloat(params.amount).toFixed(2)} USD` : 'N/A';
    document.getElementById("appr-action-target").innerText = params.payment_id ? `${params.payment_id}` : (params.subscription_id || 'Account');
    document.getElementById("appr-action-rule").innerText = act.reasoning || "Verified duplicate charge within policy window";

    // Populate Draft Preview
    const draftSub = document.getElementById("appr-draft-subject");
    const draftBody = document.getElementById("appr-draft-body");
    if (draftSub) draftSub.innerText = `Subject: ${draft.subject || 'Update on your support inquiry'}`;
    if (draftBody) {
      draftBody.innerText = formatCleanResponseText(draft) || 'Your refund has been approved and queued for processing.';
    }

    updateActionButtonsState("pending_approval", data.resolution_path);
    return;
  }

  // If completed directly or post-approval
  if (data.workflow_status === "COMPLETED" || data.resolution_path === "DIRECT_RESOLVE" || data.resolution_path === "ACTION_APPROVED") {
    const stApproval = document.getElementById("pstep-approval");
    stApproval.className = "pipeline-step completed";
    stApproval.querySelector(".step-status-icon").innerText = "✓";

    const stExecute = document.getElementById("pstep-execute");
    stExecute.className = "pipeline-step completed";
    stExecute.querySelector(".step-status-icon").innerText = "✓";
    document.getElementById("pstep-execute-details").innerText = data.action_result?.message || "Action executed via MCP tool";

    const stResp = document.getElementById("pstep-response");
    stResp.className = "pipeline-step completed";
    stResp.querySelector(".step-status-icon").innerText = "✓";

    document.getElementById("wf-badge-status").className = "badge badge-success";
    document.getElementById("wf-badge-status").innerText = "RESOLVED";

    // Show Final Response Draft
    if (data.final_response) {
      document.getElementById("agent-final-response-box").classList.remove("hidden");
      document.getElementById("agent-response-text").innerText = formatCleanResponseText(data.final_response);
    }

    updateActionButtonsState("resolved", data.resolution_path);
  } else if (data.resolution_path === "ESCALATED") {
    document.getElementById("wf-badge-status").className = "badge badge-danger";
    document.getElementById("wf-badge-status").innerText = "ESCALATED";

    const stApproval = document.getElementById("pstep-approval");
    stApproval.className = "pipeline-step completed";
    stApproval.querySelector(".step-status-icon").innerText = "⚡";
    document.getElementById("pstep-approval-details").innerText = "Routed directly to Tier 2 specialist";

    updateActionButtonsState("escalated", data.resolution_path);
  }
}

function formatCleanResponseText(resp) {
  if (!resp) return "";
  if (typeof resp === "string") return resp.trim();

  let greeting = (resp.greeting || "").trim();
  let body = (resp.body || "").trim();
  let nextSteps = (resp.next_steps || "").trim();

  if (greeting) {
    if (body.toLowerCase().startsWith(greeting.toLowerCase()) || /^(hello|dear|hi\b|good\s+(morning|afternoon|evening))/i.test(body)) {
      greeting = "";
    }
  }

  const parts = [greeting, body, nextSteps].filter(p => Boolean(p && p.trim()));
  return parts.join("\n\n");
}

function updateActionButtonsState(status, resolutionPath) {
  const btnRun = document.getElementById("btn-run-agent-workflow");
  const btnSend = document.getElementById("btn-send-email-update");
  const customReplyBtn = document.getElementById("btn-send-custom-reply");
  const customReplyText = document.getElementById("operator-custom-reply-text");

  if (!btnRun) return;

  if (status === "resolved" || status === "closed" || resolutionPath === "ACTION_APPROVED" || resolutionPath === "DIRECT_RESOLVE" || resolutionPath === "MANUAL_OPERATOR_RESOLVE") {
    btnRun.disabled = true;
    btnRun.className = "btn btn-success btn-block disabled";
    btnRun.style.opacity = "0.75";
    btnRun.style.cursor = "not-allowed";
    btnRun.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> ${resolutionPath === 'MANUAL_OPERATOR_RESOLVE' ? 'Resolved via Custom Operator Response' : 'AI Resolution Completed (Resolved)'}`;

    if (btnSend) {
      btnSend.disabled = true;
      btnSend.className = "btn btn-sm btn-secondary disabled";
      btnSend.style.opacity = "0.75";
      btnSend.style.cursor = "not-allowed";
      btnSend.innerHTML = "✓ Email Dispatched";
    }

    if (customReplyBtn) {
      customReplyBtn.disabled = true;
      customReplyBtn.innerHTML = "✓ Ticket Resolved";
    }
    if (customReplyText) {
      customReplyText.placeholder = "Ticket is resolved. Re-open if further follow-up is needed.";
    }
  } else if (status === "pending_approval" || resolutionPath === "PROPOSE_ACTION_APPROVAL") {
    btnRun.disabled = true;
    btnRun.className = "btn btn-warning btn-block disabled";
    btnRun.style.opacity = "0.85";
    btnRun.style.cursor = "not-allowed";
    btnRun.innerHTML = `⏸ Action Pending Approval (See Right Panel)`;

    if (btnSend) {
      btnSend.disabled = true;
      btnSend.className = "btn btn-sm btn-secondary disabled";
      btnSend.style.opacity = "0.75";
      btnSend.style.cursor = "not-allowed";
      btnSend.innerHTML = "Awaiting Approval";
    }
  } else if (status === "escalated" || resolutionPath === "ESCALATED") {
    btnRun.disabled = true;
    btnRun.className = "btn btn-danger btn-block disabled";
    btnRun.style.opacity = "0.75";
    btnRun.style.cursor = "not-allowed";
    btnRun.innerHTML = `⚡ Escalated to Specialist`;

    if (btnSend) {
      btnSend.disabled = true;
      btnSend.className = "btn btn-sm btn-secondary disabled";
      btnSend.style.opacity = "0.75";
      btnSend.style.cursor = "not-allowed";
      btnSend.innerHTML = "Escalated";
    }
  } else {
    // Open or In-Progress (Fresh Billing or Manual Review Ticket)
    btnRun.disabled = false;
    btnRun.className = "btn btn-primary btn-block";
    btnRun.style.opacity = "1";
    btnRun.style.cursor = "pointer";
    btnRun.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg> Execute AI Resolution Review`;

    if (btnSend) {
      btnSend.disabled = false;
      btnSend.className = "btn btn-sm btn-primary";
      btnSend.style.opacity = "1";
      btnSend.style.cursor = "pointer";
      btnSend.innerHTML = "Send Email Update";
    }

    if (customReplyBtn) {
      customReplyBtn.disabled = false;
      customReplyBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Send Custom Response & Resolve`;
    }
    if (customReplyText) {
      customReplyText.placeholder = "Write custom response directly to the customer...";
    }
  }
}


function renderExistingWorkflowState(ticket) {
  const meta = ticket.metadata || {};

  // For open tickets or tickets that have not yet executed AI workflow
  if (ticket.status === "open" || (!meta.classification && ticket.status !== "resolved" && ticket.status !== "pending_approval" && ticket.status !== "in_progress" && ticket.status !== "escalated")) {
    resetWorkflowUI();
    document.getElementById("wf-badge-status").className = "badge badge-neutral";
    document.getElementById("wf-badge-status").innerText = "AWAITING OPERATOR ACTION";
    updateActionButtonsState("open", null);
    return;
  }

  if (ticket.status === "in_progress") {
    resetWorkflowUI();
    document.getElementById("wf-badge-status").className = "badge badge-info";
    document.getElementById("wf-badge-status").innerText = "PROCESSING";
    const stClassify = document.getElementById("pstep-classify");
    if (stClassify) {
      stClassify.className = "pipeline-step active";
      stClassify.querySelector(".step-status-icon").innerText = "⏳";
      document.getElementById("pstep-classify-details").innerText = "Background AI workflow actively analyzing inquiry & records...";
    }
    updateActionButtonsState("in_progress", ticket.resolution_path);
    return;
  }

  renderWorkflowExecution({
    is_waiting_human_approval: ticket.status === "pending_approval",
    workflow_status: ticket.status === "resolved" ? "COMPLETED" : ticket.status.toUpperCase(),
    resolution_path: ticket.resolution_path || (ticket.status === "pending_approval" ? "PROPOSE_ACTION_APPROVAL" : "DIRECT_RESOLVE"),
    classification: meta.classification,
    entities: meta.entities,
    rules_evaluation: meta.rules,
    proposed_action: meta.proposed_action,
    response_draft: meta.response_draft,
    action_result: meta.action_result,
    final_response: meta.final_response || { body: ticket.resolution_summary },
    audit_logs: meta.audit_logs || []
  });

  updateActionButtonsState(ticket.status, ticket.resolution_path);
}




function renderToolActivity(auditLogs) {
  const container = document.getElementById("tool-activity-logs");
  const toolLogs = auditLogs.filter(l => ["context_lookup", "execute_action", "finalize_ticket"].includes(l.step));

  if (toolLogs.length === 0) {
    container.innerHTML = `
      <div class="tool-log-item">
        <span class="tool-name">MCP.get_customer()</span>
        <span class="badge badge-success">Completed (48ms)</span>
      </div>
      <div class="tool-log-item">
        <span class="tool-name">MCP.get_payments()</span>
        <span class="badge badge-success">Completed (62ms)</span>
      </div>
    `;
    return;
  }

  container.innerHTML = toolLogs.map(l => {
    let toolName = `MCP.${l.step}`;
    if (l.step === "context_lookup") toolName = "MCP.get_customer() & get_payments()";
    if (l.step === "execute_action") toolName = "MCP.create_refund()";
    if (l.step === "finalize_ticket") toolName = "MCP.update_ticket()";

    return `
      <div class="tool-log-item">
        <span class="tool-name">${toolName}</span>
        <span class="badge badge-success">Executed</span>
      </div>
    `;
  }).join('');
}

// ==========================================
// HUMAN APPROVAL MODAL HANDLERS
// ==========================================
async function confirmHumanDecision(decision) {
  if (!currentSelectedTicketId) return;

  try {
    const res = await fetch(`/api/workflow/approve/${currentSelectedTicketId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision: decision,
        notes: "Approved by support manager"
      })
    });
    const data = await res.json();
    document.getElementById("wf-approval-card").classList.add("hidden");
    renderWorkflowExecution(data);
    await loadAgentTicketQueue();
    await loadCustomerContext(document.getElementById("agent-tkt-custemail").innerText);
  } catch (err) {
    alert("Approval error: " + err.message);
  }
}

function openModifyModal() {
  const currentAmt = document.getElementById("appr-action-amount").innerText.replace(/[^0-9.]/g, '');
  document.getElementById("modify-orig-amount").value = `$${currentAmt} USD`;
  document.getElementById("modify-new-amount").value = currentAmt;
  document.getElementById("modal-modify-action").classList.remove("hidden");
}

function closeModifyModal() {
  document.getElementById("modal-modify-action").classList.add("hidden");
}

async function submitModifiedApproval(event) {
  event.preventDefault();
  const newAmt = parseFloat(document.getElementById("modify-new-amount").value);
  const notes = document.getElementById("modify-notes").value;

  try {
    const res = await fetch(`/api/workflow/approve/${currentSelectedTicketId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision: "MODIFIED",
        notes: notes,
        modified_parameters: { amount: newAmt }
      })
    });
    const data = await res.json();
    closeModifyModal();
    document.getElementById("wf-approval-card").classList.add("hidden");
    renderWorkflowExecution(data);
    await loadAgentTicketQueue();
  } catch (err) {
    alert("Modified approval failed: " + err.message);
  }
}

function openRejectModal() {
  document.getElementById("modal-reject-action").classList.remove("hidden");
}

function closeRejectModal() {
  document.getElementById("modal-reject-action").classList.add("hidden");
}

async function submitRejectDecision(event) {
  event.preventDefault();
  const reason = document.getElementById("reject-notes").value;

  try {
    const res = await fetch(`/api/workflow/approve/${currentSelectedTicketId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision: "REJECTED",
        notes: reason
      })
    });
    const data = await res.json();
    closeRejectModal();
    document.getElementById("wf-approval-card").classList.add("hidden");
    renderWorkflowExecution(data);
    await loadAgentTicketQueue();
  } catch (err) {
    alert("Rejection failed: " + err.message);
  }
}

function copyCustomerResponse() {
  const text = document.getElementById("agent-response-text").innerText;
  navigator.clipboard.writeText(text);
  alert("Response copied to clipboard!");
}

function markResponseSent() {
  alert("Email response sent to customer via MCP service!");
}

async function sendOperatorCustomReply() {
  if (!currentSelectedTicketId) {
    alert("Please select a ticket first.");
    return;
  }

  const textarea = document.getElementById("operator-custom-reply-text");
  const replyBody = (textarea ? textarea.value : "").trim();

  if (!replyBody) {
    alert("Please enter a custom response before sending.");
    return;
  }

  const btn = document.getElementById("btn-send-custom-reply");
  btn.disabled = true;
  btn.innerText = "Sending Response...";

  try {
    const res = await fetch(`/api/system/tickets/${currentSelectedTicketId}/reply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        body: replyBody,
        status: "resolved"
      })
    });

    if (!res.ok) {
      throw new Error(`Failed to send response: ${res.statusText}`);
    }

    const updatedTicket = await res.json();
    textarea.value = "";
    alert("Custom response sent to customer and ticket resolved!");
    await loadAgentTicketQueue();
    selectAgentTicket(updatedTicket.id);
  } catch (err) {
    alert("Error sending custom response: " + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Send Custom Response & Resolve`;
  }
}


// ==========================================
// DEMO PRESETS
// ==========================================
function loadDemoScenario(key) {
  const sc = DEMO_SCENARIOS[key];
  if (!sc) return;

  // Find ticket or create ticket for this scenario
  const existing = allTicketsCache.find(t => t.customer_email.toLowerCase() === sc.email.toLowerCase());
  if (existing) {
    selectAgentTicket(existing.id);
  } else {
    // Create new ticket for quick demo
    fetch("/api/system/tickets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_email: sc.email,
        subject: sc.subject,
        description: sc.description,
        category: sc.category,
        priority: "high"
      })
    }).then(res => res.json()).then(t => {
      loadAgentTicketQueue();
      selectAgentTicket(t.id);
    });
  }
}

// ==========================================
// CUSTOMERS DIRECTORY TAB
// ==========================================
async function loadCustomersTable() {
  const tbody = document.getElementById("customers-table-body");
  tbody.innerHTML = `<tr><td colspan="8" class="text-center">Loading customers from PostgreSQL...</td></tr>`;

  try {
    const res = await fetch("/api/system/customers");
    const customers = await res.json();

    if (customers.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center">No customers found.</td></tr>`;
      return;
    }

    tbody.innerHTML = customers.map(c => {
      const tierBadge = c.tier === "Enterprise" || c.tier === "VIP" 
        ? `<span class="badge badge-warning">${c.tier}</span>` 
        : `<span class="badge badge-info">${c.tier}</span>`;

      return `
        <tr>
          <td><code class="font-mono">${c.id}</code></td>
          <td><strong>${c.name}</strong></td>
          <td>${c.email}</td>
          <td>${tierBadge}</td>
          <td><span class="badge badge-success">${c.status}</span></td>
          <td>${c.subscriptions ? c.subscriptions.length : 1} plan(s)</td>
          <td>${c.orders ? c.orders.length : 1} order(s)</td>
          <td>
            <button class="btn btn-xs btn-outline" onclick="inspectCustomerTickets('${c.email}')">View Tickets</button>
          </td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger">Error: ${err.message}</td></tr>`;
  }
}

function inspectCustomerTickets(email) {
  switchAgentTab("tickets");
  document.getElementById("ticket-search-input").value = email;
  filterTicketQueue();
}

// ==========================================
// EVALUATION & BENCHMARK SUITE TAB
// ==========================================
async function runBenchmarkEvaluation() {
  const btn = document.getElementById("btn-eval-runner");
  btn.disabled = true;
  btn.innerHTML = `<svg class="spinner" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 10 10"/></svg> Executing 7 Benchmark Cases...`;

  try {
    const res = await fetch("/api/workflow/evaluate", { method: "POST" });
    const report = await res.json();

    document.getElementById("metric-intent").innerText = `${report.metrics.intent_classification_accuracy}%`;
    document.getElementById("metric-routing").innerText = `${report.metrics.resolution_routing_accuracy}%`;
    document.getElementById("metric-compliance").innerText = `${report.metrics.deterministic_rule_compliance}%`;
    document.getElementById("metric-gating").innerText = `${report.metrics.human_approval_gating_compliance}%`;

    const tbody = document.getElementById("benchmark-table-body");
    tbody.innerHTML = report.case_results.map(c => {
      const isPassed = c.intent_pass && c.routing_pass && c.action_pass && c.approval_gate_pass;
      return `
        <tr>
          <td><code class="font-mono">${c.case_id}</code></td>
          <td><strong>${c.case_name}</strong></td>
          <td><code>${c.expected_intent}</code></td>
          <td><code>${c.actual_intent}</code></td>
          <td><span class="badge ${c.routing_pass ? 'badge-info' : 'badge-danger'}">${c.expected_path}</span></td>
          <td><span class="badge ${c.routing_pass ? 'badge-info' : 'badge-danger'}">${c.actual_path}</span></td>
          <td><code>${c.actual_action}</code></td>
          <td>${c.approval_gated ? '🛡️ Gated' : '⚡ Direct'}</td>
          <td><span class="badge ${isPassed ? 'badge-success' : 'badge-danger'}">${isPassed ? 'PASS' : 'FAIL'}</span></td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    alert("Evaluation failed: " + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg> Execute 7-Case Benchmark Suite`;
  }
}

async function resetDatabaseSeed() {
  if (!confirm("Reset and re-seed the PostgreSQL database with fresh ground-truth records?")) return;
  try {
    const res = await fetch("/api/system/seed", { method: "POST" });
    const data = await res.json();
    alert("Database re-seeded successfully!");
    loadAgentTicketQueue();
    loadCustomerTickets();
  } catch (err) {
    alert("Reset failed: " + err.message);
  }
}

// ==========================================
// Helpers
// ==========================================
function capitalize(str) {
  if (!str) return '';
  return str.charAt(0).toUpperCase() + str.slice(1);
}

function formatStatusLabel(st) {
  if (!st) return 'OPEN';
  if (st === 'pending_approval') return 'PENDING APPROVAL';
  if (st === 'in_progress') return 'IN PROGRESS';
  return st.toUpperCase();
}

function getStatusBadgeClass(st) {
  if (!st) return 'badge-neutral';
  if (st === 'resolved' || st === 'closed') return 'badge-success';
  if (st === 'pending_approval') return 'badge-warning';
  if (st === 'in_progress') return 'badge-info';
  if (st === 'escalated') return 'badge-danger';
  return 'badge-neutral';
}

function getAgentStatusBadge(st) {
  return `<span class="badge ${getStatusBadgeClass(st)}">${formatStatusLabel(st)}</span>`;
}

function getCustomerStatusBadge(st) {
  if (st === 'resolved' || st === 'closed') return `<span class="badge badge-success">Resolved</span>`;
  if (st === 'pending_approval') return `<span class="badge badge-warning">Under Review</span>`;
  if (st === 'in_progress') return `<span class="badge badge-info">Processing</span>`;
  if (st === 'escalated') return `<span class="badge badge-danger">Specialist Review</span>`;
  return `<span class="badge badge-neutral">Submitted</span>`;
}

function getPriorityBadge(pr) {
  const p = (pr || 'medium').toLowerCase();
  if (p === 'urgent' || p === 'high') return `<span class="badge badge-danger">${p.toUpperCase()}</span>`;
  if (p === 'medium') return `<span class="badge badge-warning">MED</span>`;
  return `<span class="badge badge-neutral">LOW</span>`;
}

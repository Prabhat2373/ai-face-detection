(function () {
  const output = document.getElementById("output");
  const licenseJson = document.getElementById("licenseJson");
  const fileInput = document.getElementById("licenseFile");
  const activateBtn = document.getElementById("activateBtn");
  const loadExampleBtn = document.getElementById("loadExample");

  const setOutput = (value) => {
    output.textContent =
      typeof value === "string" ? value : JSON.stringify(value, null, 2);
  };

  loadExampleBtn?.addEventListener("click", () => {
    licenseJson.value = JSON.stringify(
      {
        payload: {
          tenantId: "acme",
          companyName: "Acme Pvt Ltd",
          plan: "pro",
          cloudSyncEnabled: true,
          issuedAt: new Date().toISOString(),
          expiresAt: null,
          machineId: null,
        },
        signature: "paste-your-signature",
        algorithm: "HS256",
      },
      null,
      2,
    );
  });

  fileInput?.addEventListener("change", async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    licenseJson.value = await file.text();
  });

  activateBtn?.addEventListener("click", async () => {
    try {
      setOutput("Activating...");
      const license = JSON.parse(licenseJson.value);
      const response = await fetch("/license/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(license),
      });
      if (!response.ok) {
        throw new Error(
          (await response.json()).error || `HTTP ${response.status}`,
        );
      }
      const activated = await response.json();

      const tenantId =
        document.getElementById("tenantId").value.trim() ||
        activated.license.payload.tenantId;
      const companyName =
        document.getElementById("companyName").value.trim() ||
        activated.license.payload.companyName;
      const adminEmail = document.getElementById("adminEmail").value.trim();
      const adminPassword = document.getElementById("adminPassword").value;
      const plan =
        document.getElementById("plan").value.trim() ||
        activated.license.payload.plan;
      const cloudSyncEnabled = Boolean(
        document.getElementById("cloudSync").checked,
      );
      const machineId =
        document.getElementById("machineId").value.trim() || null;
      const expiresAt =
        document.getElementById("expiresAt").value.trim() || null;

      const bootstrapResponse = await fetch(
        "http://localhost:5050/tenant/bootstrap",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            tenantName: companyName,
            adminEmail,
            adminPassword,
            plan,
            licenseKey: JSON.stringify(license),
            cloudSyncEnabled,
          }),
        },
      );
      if (!bootstrapResponse.ok) {
        throw new Error(
          (await bootstrapResponse.json()).error ||
            `HTTP ${bootstrapResponse.status}`,
        );
      }
      const boot = await bootstrapResponse.json();
      setOutput({
        activated,
        boot,
        tenantId,
        companyName,
        machineId,
        expiresAt,
      });
    } catch (error) {
      setOutput(error instanceof Error ? error.message : String(error));
    }
  });
})();

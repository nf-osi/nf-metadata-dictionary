/**
 * NF Auto-fill Client for Synapse Curation Grids
 *
 * This client library integrates with Synapse file view grids to provide
 * dynamic auto-fill functionality by calling the NF auto-fill service.
 *
 * Usage in Synapse:
 *   <script src="https://your-domain.com/autofill_client.js"></script>
 *   <script>
 *     const autofill = new NFAutofillClient({
 *       serviceUrl: 'https://autofill.nf-osi.org'
 *     });
 *     autofill.enable();
 *   </script>
 */

class NFAutofillClient {
  constructor(options = {}) {
    this.serviceUrl = options.serviceUrl || 'http://localhost:8000';
    this.enabled = false;
    this.cache = new Map();
    this.cacheTimeout = options.cacheTimeout || 5 * 60 * 1000; // 5 minutes

    // Configuration for which fields trigger auto-fill
    this.triggers = options.triggers || {
      'AnimalIndividualTemplate': {
        'modelSystemName': ['species', 'organism', 'genotype', 'backgroundStrain', 'RRID', 'modelSystemType', 'geneticModification', 'manifestation', 'institution']
      },
      'BiospecimenTemplate': {
        'cellLineName': ['species', 'tissue', 'organ', 'cellType', 'disease', 'RRID']
      }
    };

    this.log('Initialized', { serviceUrl: this.serviceUrl });
  }

  log(message, data = null) {
    const prefix = '[NFAutofill]';
    if (data) {
      console.log(prefix, message, data);
    } else {
      console.log(prefix, message);
    }
  }

  /**
   * Enable auto-fill functionality on the current page.
   * Attaches event listeners to detect field changes in Synapse grids.
   */
  enable() {
    if (this.enabled) {
      this.log('Already enabled');
      return;
    }

    this.enabled = true;
    this.log('Enabling auto-fill...');

    // Detect template from page
    const template = this.detectTemplate();
    if (!template) {
      this.log('Warning: Could not detect template');
      return;
    }

    this.log('Detected template:', template);
    this.currentTemplate = template;

    // Set up observers for Synapse grid changes
    this.observeGridChanges();

    this.log('✓ Auto-fill enabled');
  }

  /**
   * Detect which template is being used on the current page.
   * Looks for template name in page URL, title, or metadata.
   */
  detectTemplate() {
    // Try URL parameters
    const urlParams = new URLSearchParams(window.location.search);
    const template = urlParams.get('template');
    if (template) return template;

    // Try page title
    const title = document.title;
    for (const templateName of Object.keys(this.triggers)) {
      if (title.includes(templateName)) {
        return templateName;
      }
    }

    // Try data attributes
    const grid = document.querySelector('[data-template]');
    if (grid) {
      return grid.getAttribute('data-template');
    }

    // Default for testing
    return 'AnimalIndividualTemplate';
  }

  /**
   * Set up mutation observer to watch for grid changes.
   * This is necessary because Synapse grids are dynamically rendered.
   */
  observeGridChanges() {
    // Watch for changes to input fields in the grid
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === 'childList' || mutation.type === 'attributes') {
          this.attachFieldListeners();
        }
      }
    });

    // Observe the entire document for changes
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['value']
    });

    // Initial attachment
    this.attachFieldListeners();
  }

  /**
   * Attach change listeners to trigger fields in the grid.
   */
  attachFieldListeners() {
    const triggers = this.triggers[this.currentTemplate];
    if (!triggers) return;

    // Find input fields for trigger columns
    for (const triggerField of Object.keys(triggers)) {
      // Look for inputs with name or data-field attribute matching trigger
      const inputs = document.querySelectorAll(
        `input[name="${triggerField}"], ` +
        `input[data-field="${triggerField}"], ` +
        `select[name="${triggerField}"], ` +
        `select[data-field="${triggerField}"]`
      );

      inputs.forEach(input => {
        if (input.dataset.nfAutofillAttached) return;

        input.dataset.nfAutofillAttached = 'true';
        input.addEventListener('change', (event) => this.handleFieldChange(event, triggerField));

        this.log('Attached listener to', triggerField);
      });
    }
  }

  /**
   * Handle change event on a trigger field.
   */
  async handleFieldChange(event, triggerField) {
    const value = event.target.value;
    if (!value || value.trim() === '') return;

    this.log('Field changed:', { field: triggerField, value });

    try {
      // Get auto-fill data
      const autofillData = await this.lookup(triggerField, value);

      if (autofillData.success) {
        // Apply auto-fill to the row
        const row = this.findRowForInput(event.target);
        this.applyAutofill(row, autofillData.autofill);
      }
    } catch (error) {
      console.error('[NFAutofill] Lookup failed:', error);
    }
  }

  /**
   * Find the row container for an input element.
   */
  findRowForInput(input) {
    // Try to find parent row element
    let current = input;
    while (current) {
      if (current.tagName === 'TR' || current.classList.contains('grid-row')) {
        return current;
      }
      current = current.parentElement;
    }
    return null;
  }

  /**
   * Apply auto-fill values to fields in a row.
   */
  applyAutofill(row, autofillData) {
    if (!row) {
      this.log('Warning: No row found for auto-fill');
      return;
    }

    this.log('Applying auto-fill:', autofillData);

    for (const [field, value] of Object.entries(autofillData)) {
      // Find input for this field in the row
      const input = row.querySelector(
        `input[name="${field}"], ` +
        `input[data-field="${field}"], ` +
        `select[name="${field}"], ` +
        `select[data-field="${field}"], ` +
        `textarea[name="${field}"], ` +
        `textarea[data-field="${field}"]`
      );

      if (input && input.value === '') {
        // Only fill if field is empty
        input.value = value;
        input.dispatchEvent(new Event('change', { bubbles: true }));

        this.log('  ✓ Filled', field, '=', value);
      }
    }
  }

  /**
   * Look up auto-fill values from the service.
   */
  async lookup(triggerField, triggerValue) {
    // Check cache first
    const cacheKey = `${this.currentTemplate}:${triggerField}:${triggerValue}`;
    const cached = this.cache.get(cacheKey);
    if (cached && Date.now() - cached.timestamp < this.cacheTimeout) {
      this.log('Cache hit for', cacheKey);
      return cached.data;
    }

    // Call service
    const url = `${this.serviceUrl}/api/v1/autofill`;
    const body = {
      template: this.currentTemplate,
      trigger_field: triggerField,
      trigger_value: triggerValue
    };

    this.log('Calling service:', url, body);

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();

    // Cache result
    this.cache.set(cacheKey, {
      data,
      timestamp: Date.now()
    });

    return data;
  }

  /**
   * Get enum values for a field from the service.
   */
  async getEnumValues(field) {
    const url = `${this.serviceUrl}/api/v1/enums/${this.currentTemplate}/${field}`;

    this.log('Fetching enum values:', url);

    const response = await fetch(url);

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    return data.values;
  }

  /**
   * Disable auto-fill functionality.
   */
  disable() {
    this.enabled = false;
    this.log('Auto-fill disabled');
  }

  /**
   * Check if service is available.
   */
  async healthCheck() {
    const url = `${this.serviceUrl}/health`;

    try {
      const response = await fetch(url);
      return response.ok;
    } catch (error) {
      return false;
    }
  }
}

// Export for use in modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = NFAutofillClient;
}

// Make available globally
if (typeof window !== 'undefined') {
  window.NFAutofillClient = NFAutofillClient;
}

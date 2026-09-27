export default function App() {
  return (
    <main className="foundation-page ux4g-container ux4g-grid ux4g-gap-xl ux4g-p-m ux4g-xl-p-xl">
      <span className="ux4g-tag-tonal-neutral ux4g-tag-s">Local demo foundation</span>
      <section
        className="ux4g-card ux4g-card-solid ux4g-card-vertical foundation-card"
        aria-labelledby="foundation-title"
      >
        <div className="ux4g-card-body ux4g-grid ux4g-gap-m">
          <p className="ux4g-label-m-strong ux4g-text-brand-primary-default">MIRROR · HOUSEHOLD FINANCIAL CLARITY</p>
          <h1 id="foundation-title">A clearer view of what your household pays and receives.</h1>
          <p>
            This local demo is being prepared with sample data. It does not connect to a bank or
            initiate an Account Aggregator consent.
          </p>
          <div className="ux4g-alert ux4g-alert-info" role="note">
            <span>Illustrative demo only · no live account is connected</span>
          </div>
          <button className="ux4g-btn ux4g-btn-primary ux4g-btn-md" type="button" disabled>
            Demo journey is being prepared
          </button>
        </div>
      </section>
    </main>
  );
}

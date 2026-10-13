import { t, useLang } from "../i18n";

/* Data credits: "Data provided by the National Library Board, Singapore (NLB)" linked to NLB Labs,
   and the NLB datasets and APIs PreReads uses. The credit line stays in English in every language. */
const NLB_LABS = "https://www.nlb.gov.sg/main/partner-us/contribute-and-create-with-us/NLBLabs";
const SOURCES = {
  libraries: "https://data.gov.sg/datasets/d_27b8dae65d9ca1539e14d09578b17cbf/view",
  stats: "https://data.gov.sg/datasets/d_bf36da418f88e5485aff69079694ecef/view",
  hours: "https://www.nlb.gov.sg/main/visit-us/our-libraries-and-locations",
  ebooks: "https://nlb.overdrive.com",
};

export default function Footer() {
  useLang();
  const link = (href: string, label: string) => (
    <a href={href} target="_blank" rel="noopener">
      {label}
    </a>
  );
  return (
    <footer className="footer">
      <p>{t("home.footer")}</p>
      <p className="footer-credit">{link(NLB_LABS, "Data provided by the National Library Board, Singapore (NLB)")}</p>
      <p className="footer-sources">
        {t("footer.sources")} {link(SOURCES.libraries, "Libraries")} · {link(SOURCES.stats, "NLB Library Reach Index, Collections and Loans")} (data.gov.sg) ·{" "}
        {link(SOURCES.hours, t("footer.hours"))} · {link(SOURCES.ebooks, t("footer.ebooks"))}
      </p>
    </footer>
  );
}

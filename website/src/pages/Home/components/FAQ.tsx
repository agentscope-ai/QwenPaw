import { useMemo, useState } from "react";
import { motion } from "motion/react";

type FaqCategory = "quickStart" | "account" | "features";

type FaqItem = {
  id: string;
  question: string;
  answer: string;
};

const sectionVariants = {
  hidden: { opacity: 0, y: 16 },
  show: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.45,
      ease: "easeOut",
      when: "beforeChildren",
      staggerChildren: 0.08,
    },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 10 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.35, ease: "easeOut" },
  },
};

const categories: Array<{ key: FaqCategory; label: string }> = [
  { key: "quickStart", label: "Quick Start" },
  { key: "account", label: "Account & security" },
  { key: "features", label: "Features & tools" },
];

const faqData: Record<FaqCategory, FaqItem[]> = {
  quickStart: [
    {
      id: "install",
      question: "How to install CoPaw?",
      answer:
        "Memory and personalization under your control. Deploy locally or in the cloud; scheduled reminders and collaboration to any channel.",
    },
    { id: "update", question: "How to update CoPaw?", 
      answer:
        "Memory and personalization under your control. Deploy locally or in the cloud; scheduled reminders and collaboration to any channel.", },
    {
      id: "initialize",
      question: "How to initialize and start CoPaw service?",
      answer:
        "Memory and personalization under your control. Deploy locally or in the cloud; scheduled reminders and collaboration to any channel.",
    },
    {
      id: "upgrade",
      question: "Where to check latest version upgrade details?",
      answer:
        "Memory and personalization under your control. Deploy locally or in the cloud; scheduled reminders and collaboration to any channel.",
    },
    { id: "models", question: "How to configure models?",
      answer:
        "Memory and personalization under your control. Deploy locally or in the cloud; scheduled reminders and collaboration to any channel.",},
    {
      id: "cron",
      question: "Troubleshooting scheduled (cron) tasks",
      answer:
        "Memory and personalization under your control. Deploy locally or in the cloud; scheduled reminders and collaboration to any channel.",
    },
  ],
  account: [
    {
      id: "account-security",
      question: "How to keep my account secure?",
      answer:
        "Use strong credentials, rotate API keys regularly, and limit permissions for integrations.",
    },
    {
      id: "backup",
      question: "How to back up my local data?",
      answer:
        "Memory and personalization under your control. Deploy locally or in the cloud; scheduled reminders and collaboration to any channel.",
    },
    {
      id: "privacy",
      question: "Can I control where my data is stored?",
      answer:
        "Memory and personalization under your control. Deploy locally or in the cloud; scheduled reminders and collaboration to any channel.",
    },
  ],
  features: [
    {
      id: "channels",
      question: "Which channels does CoPaw support?",
      answer:
        "CoPaw supports multiple channels and can connect through extensible integrations.",
    },
    {
      id: "skills",
      question: "How to add custom skills?",
      answer:
        "Memory and personalization under your control. Deploy locally or in the cloud; scheduled reminders and collaboration to any channel.",
    },
    {
      id: "automation",
      question: "Can I automate repeated workflows?",
      answer:
        "Memory and personalization under your control. Deploy locally or in the cloud; scheduled reminders and collaboration to any channel.",
    },
  ],
};

export function CopawFAQ() {
  const [activeCategory, setActiveCategory] =
    useState<FaqCategory>("quickStart");
  const [openId, setOpenId] = useState("install");

  const currentFaqs = useMemo(() => faqData[activeCategory], [activeCategory]);

  return (
    <motion.section
      className="px-4 py-9 md:py-14"
      variants={sectionVariants}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, amount: 0.2 }}
      aria-labelledby="copaw-faq-heading"
    >
      <div className="mx-auto max-w-7xl">
        <div className="grid gap-8 md:grid-cols-2 md:gap-12">
          <motion.div variants={itemVariants}>
            <h2
              id="copaw-faq-heading"
              className="font-newsreader text-[1.7rem] leading-[1.2] text-(--color-text) sm:text-[1.9rem] md:text-[2.75rem]"
            >
              Frequently asked questions
            </h2>
            <p className="font-inter mt-2 text-[13px] leading-relaxed text-(--color-text-tertiary) md:text-[1rem]">
              Memory and personalization under your control.
            </p>

            <div className="mt-5 flex flex-wrap gap-2 md:mt-6 md:block md:border-l-2 md:border-[#e9dfd6] md:pl-0.5">
              {categories.map((category) => {
                const active = category.key === activeCategory;
                return (
                  <button
                    key={category.key}
                    type="button"
                    onClick={() => {
                      setActiveCategory(category.key);
                      setOpenId(faqData[category.key][0]?.id ?? "");
                    }}
                    className={`relative inline-flex w-fit items-center rounded-full px-3 py-1.5 text-left text-[1rem] leading-[1.2] transition md:block md:w-full md:rounded-none md:py-5 md:pl-3 md:pr-0 md:text-[1.95rem] md:leading-[1.05] ${
                      active
                        ? "font-newsreader bg-[rgba(236,146,69,0.12)] text-(--color-primary) md:bg-transparent"
                        : "font-newsreader text-(--color-text)"
                    }`}
                  >
                    {active ? (
                      <span className="absolute bottom-0 -left-1 top-0 hidden w-0.5 bg-(--color-primary) md:block" />
                    ) : null}
                    {category.label}
                  </button>
                );
              })}
            </div>
          </motion.div>

          <motion.div className="md:pt-1" variants={itemVariants}>
            <p className="font-inter mb-4 max-w-xl text-[13px] leading-relaxed text-(--color-text-secondary) md:mb-5 md:text-[1rem]">
              Here's everything you need to know to get started, manage your
              account, and troubleshoot the most frequent issues.
            </p>

            <div className="space-y-1.5 md:space-y-2">
              {currentFaqs.map((faq) => {
                const isOpen = faq.id === openId;
                return (
                  <div
                    key={faq.id}
                    className={`transition ${
                      isOpen
                        ? "rounded-xl bg-[#f7f3ef]"
                        : "rounded-none bg-transparent"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => setOpenId(isOpen ? "" : faq.id)}
                      className={`flex w-full items-center justify-between gap-4 text-left ${
                        isOpen
                          ? "px-3.5 pb-1.5 pt-3.5 md:px-5 md:pb-2 md:pt-4"
                          : "px-3.5 py-2.5 md:px-5 md:py-3.5"
                      }`}
                    >
                      <span className="font-newsreader text-[1.75rem] leading-[1.08] text-(--color-text) md:text-[28px]">
                        {faq.question}
                      </span>
                      <span
                        aria-hidden
                        className="font-inter text-[1.5rem] leading-none text-(--color-text) md:text-[1.85rem]"
                      >
                        {isOpen ? "−" : "+"}
                      </span>
                    </button>
                    {isOpen && faq.answer ? (
                      <div className="px-3.5 pb-3.5 md:px-5 md:pb-5">
                        <p className="font-inter text-[13px] leading-[1.65] text-(--color-text-secondary) md:text-base">
                          {faq.answer}
                        </p>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </motion.div>
        </div>
      </div>
    </motion.section>
  );
}

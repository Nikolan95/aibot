/* eslint-disable no-undef */
(function () {
  const dbName = "aibot";
  const col = "faqs";

  const items = [
    { question: "How do returns work?", answer: "PLEASE INSERT..." },
    { question: "Where is MotoParts located?", answer: "Kunerolgasse 1A, 1230 Vienna, Austria." },
    {
      question: "How can I contact you?",
      answer:
        "General email: office@motoparts.co.at\n" +
        "Parts orders via email: teilebestellung@motoparts.co.at\n" +
        "WhatsApp/Phone parts orders: +43 660 670 6970\n" +
        "Customer service: +43 660 90100 45 / 46 / 47",
    },
    { question: "Can I order or inquire via WhatsApp?", answer: "Yes, orders and inquiries are possible via WhatsApp." },
    { question: "What product categories do you offer?", answer: "Motor oils & fluids, spare parts, professional tools, and tires." },
    {
      question: "Which brands do you work with?",
      answer:
        "Among others, BOSCH, CLEAN FILTERS, MAHLE, LUK, HELLA, FEBI, CONTITECH, METELLI, NRF, NTN, POWERMAX, SCHAEFFLER, VARTA, VALEO, SONAX, SNR, SKF, VICTOR REINZ, ZF, TQ, and AISIN.",
    },
    {
      question: "Why should I buy from MotoParts?",
      answer:
        "Years of workshop experience, professional advice, quality parts, and fair prices – we'll find the right solution for your vehicle.",
    },
    {
      question: "Where can I find the legal notice and privacy policy?",
      answer: "Both pages are linked in the footer of motoparts.co.at.",
    },
    { question: "What are your opening hours?", answer: "Monday to Friday from 8:00 a.m. to 5:00 p.m." },
  ];

  const dbo = db.getSiblingDB(dbName);
  const c = dbo.getCollection(col);

  c.createIndex({ question: "text", answer: "text" }, { name: "faq_text" });
  c.createIndex({ question: 1 }, { unique: true, name: "faq_question_unique" });

  for (const it of items) {
    c.updateOne(
      { question: it.question },
      {
        $set: {
          question: it.question,
          answer: it.answer,
          enabled: true,
          updated_at: new Date(),
        },
        $setOnInsert: { created_at: new Date() },
      },
      { upsert: true },
    );
  }
})();


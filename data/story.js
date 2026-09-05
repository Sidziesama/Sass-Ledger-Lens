window.LEDGERLENS_DATA = {
  periods: [
    {
      from: "2026-07",
      to: "2026-08",
      label: "July to August close review",
      context: "Enterprise expansion, cloud migration, and cash-flow pressure",
      memoryIds: ["aws-migration", "enterprise-pricing", "acme-late"],
      expectedCloudBaselineIncrease: 26000,
      learnedAfterRun: {
        title: "Enterprise growth is concentrated",
        detail: "August growth depended heavily on Acme, Globex, and Stark; future revenue explanations must check customer concentration before saying growth is broad-based."
      }
    },
    {
      from: "2026-08",
      to: "2026-09",
      label: "August to September close review",
      context: "Repeat enterprise growth with abnormal inference spend",
      memoryIds: ["aws-migration", "enterprise-pricing", "acme-late", "enterprise-concentration"],
      expectedCloudBaselineIncrease: 10000,
      learnedAfterRun: {
        title: "Vector inference is now a margin risk",
        detail: "September compute spend exceeded the migration baseline again; future reviews should split expected migration cost from product inference cost."
      }
    }
  ],
  memory: {
    "aws-migration": {
      title: "Cloud migration budget",
      detail: "Finance reviewer approved expected incremental cloud cost of $26,000 in August and $10,000 in September. This is business context, not causal proof."
    },
    "enterprise-pricing": {
      title: "Enterprise pricing changed August 1",
      detail: "New enterprise packaging can create larger expansion invoices. Check segment and customer concentration before calling growth broad-based."
    },
    "acme-late": {
      title: "Acme historically pays late",
      detail: "Acme's average payment delay moved from 4 days to 17 days in the prior review. Cash-flow explanations should inspect collections timing."
    },
    "enterprise-concentration": {
      title: "Enterprise concentration risk",
      detail: "Prior run found that three enterprise customers drove most revenue growth. Prosecutor now rejects broad-growth claims without concentration evidence."
    }
  },
  summaries: [
    { month: "2026-07", account: "Revenue", amount: 1000000 },
    { month: "2026-07", account: "COGS", amount: 420000 },
    { month: "2026-07", account: "Cloud Costs", amount: 82000 },
    { month: "2026-07", account: "Marketing", amount: 90000 },
    { month: "2026-07", account: "Payroll", amount: 260000 },
    { month: "2026-07", account: "Operating Cash Flow", amount: 120000 },

    { month: "2026-08", account: "Revenue", amount: 1180000 },
    { month: "2026-08", account: "COGS", amount: 515000 },
    { month: "2026-08", account: "Cloud Costs", amount: 121000 },
    { month: "2026-08", account: "Marketing", amount: 88000 },
    { month: "2026-08", account: "Payroll", amount: 275000 },
    { month: "2026-08", account: "Operating Cash Flow", amount: -190000 },

    { month: "2026-09", account: "Revenue", amount: 1293000 },
    { month: "2026-09", account: "COGS", amount: 584000 },
    { month: "2026-09", account: "Cloud Costs", amount: 160000 },
    { month: "2026-09", account: "Marketing", amount: 92000 },
    { month: "2026-09", account: "Payroll", amount: 277000 },
    { month: "2026-09", account: "Operating Cash Flow", amount: -245000 }
  ],
  transactions: [
    { id: "REV-0701", date: "2026-07-03", month: "2026-07", account: "Revenue", counterparty: "Acme Corp", segment: "Enterprise", category: "Expansion", amount: 72000, status: "posted" },
    { id: "REV-0702", date: "2026-07-04", month: "2026-07", account: "Revenue", counterparty: "Globex", segment: "Enterprise", category: "Subscription", amount: 64000, status: "posted" },
    { id: "REV-0703", date: "2026-07-06", month: "2026-07", account: "Revenue", counterparty: "Stark Industries", segment: "Enterprise", category: "Subscription", amount: 35000, status: "posted" },
    { id: "REV-0704", date: "2026-07-09", month: "2026-07", account: "Revenue", counterparty: "Orion Freight", segment: "Enterprise", category: "Usage", amount: 88000, status: "posted" },
    { id: "REV-0705", date: "2026-07-16", month: "2026-07", account: "Revenue", counterparty: "Northwind", segment: "Enterprise", category: "Subscription", amount: 231000, status: "posted" },
    { id: "REV-0706", date: "2026-07-21", month: "2026-07", account: "Revenue", counterparty: "SMB Portfolio", segment: "SMB", category: "Subscription", amount: 360000, status: "posted" },
    { id: "REV-0707", date: "2026-07-28", month: "2026-07", account: "Revenue", counterparty: "Consumer Portfolio", segment: "Consumer", category: "Subscription", amount: 150000, status: "posted" },

    { id: "REV-0801", date: "2026-08-03", month: "2026-08", account: "Revenue", counterparty: "Acme Corp", segment: "Enterprise", category: "Expansion", amount: 124000, status: "posted" },
    { id: "REV-0802", date: "2026-08-05", month: "2026-08", account: "Revenue", counterparty: "Globex", segment: "Enterprise", category: "Expansion", amount: 105000, status: "posted" },
    { id: "REV-0803", date: "2026-08-07", month: "2026-08", account: "Revenue", counterparty: "Stark Industries", segment: "Enterprise", category: "Usage", amount: 58000, status: "posted" },
    { id: "REV-0804", date: "2026-08-10", month: "2026-08", account: "Revenue", counterparty: "Orion Freight", segment: "Enterprise", category: "Usage", amount: 109000, status: "posted" },
    { id: "REV-0805", date: "2026-08-18", month: "2026-08", account: "Revenue", counterparty: "Northwind", segment: "Enterprise", category: "Subscription", amount: 252000, status: "posted" },
    { id: "REV-0806", date: "2026-08-22", month: "2026-08", account: "Revenue", counterparty: "SMB Portfolio", segment: "SMB", category: "Subscription", amount: 391000, status: "posted" },
    { id: "REV-0807", date: "2026-08-29", month: "2026-08", account: "Revenue", counterparty: "Consumer Portfolio", segment: "Consumer", category: "Subscription", amount: 141000, status: "posted" },

    { id: "REV-0901", date: "2026-09-03", month: "2026-09", account: "Revenue", counterparty: "Acme Corp", segment: "Enterprise", category: "Expansion", amount: 151000, status: "posted" },
    { id: "REV-0902", date: "2026-09-04", month: "2026-09", account: "Revenue", counterparty: "Globex", segment: "Enterprise", category: "Expansion", amount: 126000, status: "posted" },
    { id: "REV-0903", date: "2026-09-08", month: "2026-09", account: "Revenue", counterparty: "Stark Industries", segment: "Enterprise", category: "Usage", amount: 67000, status: "posted" },
    { id: "REV-0904", date: "2026-09-11", month: "2026-09", account: "Revenue", counterparty: "Orion Freight", segment: "Enterprise", category: "Usage", amount: 121000, status: "posted" },
    { id: "REV-0905", date: "2026-09-18", month: "2026-09", account: "Revenue", counterparty: "Northwind", segment: "Enterprise", category: "Subscription", amount: 281000, status: "posted" },
    { id: "REV-0906", date: "2026-09-22", month: "2026-09", account: "Revenue", counterparty: "SMB Portfolio", segment: "SMB", category: "Subscription", amount: 403000, status: "posted" },
    { id: "REV-0907", date: "2026-09-28", month: "2026-09", account: "Revenue", counterparty: "Consumer Portfolio", segment: "Consumer", category: "Subscription", amount: 144000, status: "posted" },

    { id: "COGS-0701", date: "2026-07-30", month: "2026-07", account: "COGS", counterparty: "Fulfillment Network", segment: "Operations", category: "Delivery", amount: 284000, status: "posted" },
    { id: "COGS-0702", date: "2026-07-30", month: "2026-07", account: "COGS", counterparty: "Data Labeling Co", segment: "Operations", category: "Data", amount: 136000, status: "posted" },
    { id: "COGS-0801", date: "2026-08-30", month: "2026-08", account: "COGS", counterparty: "Fulfillment Network", segment: "Operations", category: "Delivery", amount: 342000, status: "posted" },
    { id: "COGS-0802", date: "2026-08-30", month: "2026-08", account: "COGS", counterparty: "Data Labeling Co", segment: "Operations", category: "Data", amount: 173000, status: "posted" },
    { id: "COGS-0901", date: "2026-09-30", month: "2026-09", account: "COGS", counterparty: "Fulfillment Network", segment: "Operations", category: "Delivery", amount: 386000, status: "posted" },
    { id: "COGS-0902", date: "2026-09-30", month: "2026-09", account: "COGS", counterparty: "Data Labeling Co", segment: "Operations", category: "Data", amount: 198000, status: "posted" },

    { id: "CLD-0701", date: "2026-07-30", month: "2026-07", account: "Cloud Costs", counterparty: "AWS Compute", segment: "Infrastructure", category: "Compute", amount: 51000, status: "posted" },
    { id: "CLD-0702", date: "2026-07-30", month: "2026-07", account: "Cloud Costs", counterparty: "AWS Storage", segment: "Infrastructure", category: "Storage", amount: 16000, status: "posted" },
    { id: "CLD-0703", date: "2026-07-30", month: "2026-07", account: "Cloud Costs", counterparty: "VectorDB Labs", segment: "Infrastructure", category: "Inference", amount: 15000, status: "posted" },
    { id: "CLD-0801", date: "2026-08-30", month: "2026-08", account: "Cloud Costs", counterparty: "AWS Compute", segment: "Infrastructure", category: "Compute", amount: 74000, status: "posted" },
    { id: "CLD-0802", date: "2026-08-30", month: "2026-08", account: "Cloud Costs", counterparty: "AWS Storage", segment: "Infrastructure", category: "Storage", amount: 19000, status: "posted" },
    { id: "CLD-0803", date: "2026-08-30", month: "2026-08", account: "Cloud Costs", counterparty: "VectorDB Labs", segment: "Infrastructure", category: "Inference", amount: 28000, status: "posted" },
    { id: "CLD-0901", date: "2026-09-30", month: "2026-09", account: "Cloud Costs", counterparty: "AWS Compute", segment: "Infrastructure", category: "Compute", amount: 84000, status: "posted" },
    { id: "CLD-0902", date: "2026-09-30", month: "2026-09", account: "Cloud Costs", counterparty: "AWS Storage", segment: "Infrastructure", category: "Storage", amount: 22000, status: "posted" },
    { id: "CLD-0903", date: "2026-09-30", month: "2026-09", account: "Cloud Costs", counterparty: "VectorDB Labs", segment: "Infrastructure", category: "Inference", amount: 54000, status: "posted" },
    { id: "CLD-0903-DUP", duplicateOf: "CLD-0903", date: "2026-09-30", month: "2026-09", account: "Cloud Costs", counterparty: "VectorDB Labs", segment: "Infrastructure", category: "Inference", amount: 54000, status: "duplicate" },

    { id: "MKT-0701", date: "2026-07-20", month: "2026-07", account: "Marketing", counterparty: "Search Ads", segment: "Growth", category: "Paid Media", amount: 70000, status: "posted" },
    { id: "MKT-0702", date: "2026-07-24", month: "2026-07", account: "Marketing", counterparty: "Events", segment: "Growth", category: "Field", amount: 20000, status: "posted" },
    { id: "MKT-0801", date: "2026-08-20", month: "2026-08", account: "Marketing", counterparty: "Search Ads", segment: "Growth", category: "Paid Media", amount: 64000, status: "posted" },
    { id: "MKT-0802", date: "2026-08-24", month: "2026-08", account: "Marketing", counterparty: "Events", segment: "Growth", category: "Field", amount: 24000, status: "posted" },
    { id: "MKT-0901", date: "2026-09-20", month: "2026-09", account: "Marketing", counterparty: "Search Ads", segment: "Growth", category: "Paid Media", amount: 62000, status: "posted" },
    { id: "MKT-0902", date: "2026-09-24", month: "2026-09", account: "Marketing", counterparty: "Events", segment: "Growth", category: "Field", amount: 30000, status: "posted" },

    { id: "PAY-0701", date: "2026-07-15", month: "2026-07", account: "Payroll", counterparty: "Payroll Provider", segment: "People", category: "Salary", amount: 260000, status: "posted" },
    { id: "PAY-0801", date: "2026-08-15", month: "2026-08", account: "Payroll", counterparty: "Payroll Provider", segment: "People", category: "Salary", amount: 275000, status: "posted" },
    { id: "PAY-0901", date: "2026-09-15", month: "2026-09", account: "Payroll", counterparty: "Payroll Provider", segment: "People", category: "Salary", amount: 277000, status: "posted" },

    { id: "OCF-0701", date: "2026-07-31", month: "2026-07", account: "Operating Cash Flow", counterparty: "Collections", segment: "Cash", category: "AR", amount: 420000, status: "posted" },
    { id: "OCF-0702", date: "2026-07-31", month: "2026-07", account: "Operating Cash Flow", counterparty: "Vendor Payments", segment: "Cash", category: "AP", amount: -265000, status: "posted" },
    { id: "OCF-0703", date: "2026-07-31", month: "2026-07", account: "Operating Cash Flow", counterparty: "Payroll", segment: "Cash", category: "Payroll", amount: -35000, status: "posted" },
    { id: "OCF-0801", date: "2026-08-31", month: "2026-08", account: "Operating Cash Flow", counterparty: "Collections", segment: "Cash", category: "AR", amount: 210000, status: "posted" },
    { id: "OCF-0802", date: "2026-08-31", month: "2026-08", account: "Operating Cash Flow", counterparty: "Vendor Payments", segment: "Cash", category: "AP", amount: -330000, status: "posted" },
    { id: "OCF-0803", date: "2026-08-31", month: "2026-08", account: "Operating Cash Flow", counterparty: "Payroll", segment: "Cash", category: "Payroll", amount: -70000, status: "posted" },
    { id: "OCF-0901", date: "2026-09-30", month: "2026-09", account: "Operating Cash Flow", counterparty: "Collections", segment: "Cash", category: "AR", amount: 235000, status: "posted" },
    { id: "OCF-0902", date: "2026-09-30", month: "2026-09", account: "Operating Cash Flow", counterparty: "Vendor Payments", segment: "Cash", category: "AP", amount: -382000, status: "posted" },
    { id: "OCF-0903", date: "2026-09-30", month: "2026-09", account: "Operating Cash Flow", counterparty: "Payroll", segment: "Cash", category: "Payroll", amount: -98000, status: "posted" }
  ]
};

import { CompanyDetail } from "./ui";

export default async function CompanyPage({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;
  return <CompanyDetail ticker={decodeURIComponent(ticker)} />;
}



import { NextResponse } from "next/server";

export async function POST() {
  const token = process.env.GITHUB_TOKEN;

  if (!token) {
    return NextResponse.json(
      { success: false, error: "GITHUB_TOKEN not configured. Add it in Vercel environment variables." },
      { status: 500 }
    );
  }

  try {
    const res = await fetch(
      "https://api.github.com/repos/shafayatsaad/webscrap/actions/workflows/scrape_and_deploy.yml/dispatches",
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github.v3+json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: "main" }),
      }
    );

    if (res.status === 204) {
      return NextResponse.json({ success: true, message: "Scraper triggered successfully" });
    } else {
      const errorText = await res.text();
      return NextResponse.json(
        { success: false, error: `GitHub API returned ${res.status}: ${errorText}` },
        { status: res.status }
      );
    }
  } catch (error) {
    return NextResponse.json(
      { success: false, error: `Failed to trigger scraper: ${String(error)}` },
      { status: 500 }
    );
  }
}

import { createClient } from "npm:@supabase/supabase-js@2.112.3";
import { createPortfolioSignalsHandler } from "./handler.mjs";

Deno.serve(createPortfolioSignalsHandler({
  createClient,
  env: (name: string) => Deno.env.get(name),
}));

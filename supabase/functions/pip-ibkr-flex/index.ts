import { createClient } from "npm:@supabase/supabase-js@2.112.3";
import { createFlexHandler } from "./handler.mjs";

Deno.serve(createFlexHandler({
  createClient,
  env: (name: string) => Deno.env.get(name),
}));

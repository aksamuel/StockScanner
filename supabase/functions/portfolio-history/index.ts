import { createClient } from "npm:@supabase/supabase-js@2.112.3";
import { createHistoryHandler } from "./handler.mjs";

Deno.serve(createHistoryHandler({ createClient, env: (name: string) => Deno.env.get(name) }));

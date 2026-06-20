import { useQuery } from "@tanstack/react-query"
import { fetchMe } from "./api"

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: fetchMe, retry: false })
}

import { useEffect, useState } from "react";
import { api } from "../api";
import type { Job } from "../api/types";

/** Live status of a background job: pushed events, with a 1 s poll as a fallback. */
export function useJob(jobId: string | null): Job | null {
  const [job, setJob] = useState<Job | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let alive = true;
    const unsubscribe = api.onEvent((event) => {
      if (event.name === "job" && event.payload.id === jobId && alive) setJob(event.payload);
    });
    const poll = () =>
      api.getJob(jobId).then(
        (j) => alive && setJob(j),
        () => undefined,
      );
    poll();
    const timer = setInterval(poll, 1000);
    return () => {
      alive = false;
      unsubscribe();
      clearInterval(timer);
    };
  }, [jobId]);

  return jobId && job?.id === jobId ? job : null;
}

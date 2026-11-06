import { useCallback, useEffect, useRef, useState } from "react";
import { chatApi } from "../api/modules/chat";
import type { ChatSearchMode, ChatSearchResponse } from "../api/types/chat";

interface SearchState {
  key: string;
  response: ChatSearchResponse | null;
  loading: boolean;
  error: boolean;
  nextOffset: number;
}

const EMPTY_STATE: SearchState = {
  key: "",
  response: null,
  loading: false,
  error: false,
  nextOffset: 0,
};

export function useConversationSearch(agentId: string) {
  const [input, setInput] = useState({
    agentId,
    query: "",
    mode: "keyword" as ChatSearchMode,
    submitted: false,
    revision: 0,
  });
  // Hide the previous owner's input and results on the first render of an
  // agent switch, before effect cleanup or an outstanding request can finish.
  const query = input.agentId === agentId ? input.query : "";
  const mode = input.agentId === agentId ? input.mode : "keyword";
  const trimmedQuery = query.trim();
  const requested = mode === "keyword" || input.submitted;
  const key = JSON.stringify([agentId, mode, query]);
  const currentKey = useRef(key);
  currentKey.current = key;
  const controller = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const [state, setState] = useState<SearchState>(EMPTY_STATE);

  useEffect(() => {
    setInput({
      agentId,
      query: "",
      mode: "keyword",
      submitted: false,
      revision: 0,
    });
  }, [agentId]);

  const cancel = useCallback(() => {
    sequence.current += 1;
    controller.current?.abort();
  }, []);

  const run = useCallback(
    async (offset = 0, previous: ChatSearchResponse | null = null) => {
      cancel();
      const requestSequence = sequence.current;
      const abortController = new AbortController();
      controller.current = abortController;
      setState({
        key,
        response: previous,
        loading: true,
        error: false,
        nextOffset: offset,
      });
      try {
        const response = await chatApi.searchChats(
          { query: trimmedQuery, mode, limit: 20, offset },
          { agentId, signal: abortController.signal },
        );
        if (requestSequence !== sequence.current || currentKey.current !== key)
          return;
        // Dedupe if the history changes between pages, retaining API order.
        const seen = new Set<string>();
        const results = previous
          ? [...previous.results, ...response.results].filter((result) => {
              if (seen.has(result.chat.id)) return false;
              seen.add(result.chat.id);
              return true;
            })
          : response.results;
        setState({
          key,
          response: { ...response, results },
          loading: false,
          error: false,
          nextOffset: offset + response.results.length,
        });
      } catch {
        if (requestSequence !== sequence.current || currentKey.current !== key)
          return;
        setState({
          key,
          response: previous,
          loading: false,
          error: true,
          nextOffset: offset,
        });
      }
    },
    [agentId, cancel, key, mode, trimmedQuery],
  );

  useEffect(() => {
    if (!trimmedQuery || !requested) return;
    setState({ ...EMPTY_STATE, key, loading: true });
    const timer = window.setTimeout(
      () => void run(),
      mode === "keyword" ? 275 : 0,
    );
    return () => {
      window.clearTimeout(timer);
      cancel();
    };
  }, [cancel, input.revision, key, mode, requested, run, trimmedQuery]);

  const setQuery = useCallback(
    (value: string) => {
      if (value === query) return;
      cancel();
      setState(EMPTY_STATE);
      setInput((previous) => ({
        ...previous,
        agentId,
        query: value,
        submitted: false,
      }));
    },
    [agentId, cancel, query],
  );

  const setMode = useCallback(
    (value: ChatSearchMode) => {
      if (value === mode) return;
      cancel();
      setState(EMPTY_STATE);
      setInput((previous) => ({
        ...previous,
        agentId,
        mode: value,
        submitted: false,
      }));
    },
    [agentId, cancel, mode],
  );

  const submit = useCallback(() => {
    if (!trimmedQuery) return;
    setInput((previous) => ({
      ...previous,
      submitted: true,
      revision: previous.revision + 1,
    }));
  }, [trimmedQuery]);

  const visibleState = state.key === key && requested ? state : EMPTY_STATE;
  const loadMore = useCallback(() => {
    if (
      mode === "keyword" &&
      visibleState.response?.has_more &&
      !visibleState.loading
    ) {
      void run(visibleState.nextOffset, visibleState.response);
    }
  }, [mode, run, visibleState]);

  return {
    query,
    mode,
    setQuery,
    setMode,
    submit,
    loadMore,
    response: visibleState.response,
    loading:
      !!trimmedQuery &&
      requested &&
      (state.key !== key || visibleState.loading),
    error: visibleState.error,
    active: !!trimmedQuery,
    awaitingSubmit: !!trimmedQuery && !requested,
  };
}

export type ConversationSearch = ReturnType<typeof useConversationSearch>;

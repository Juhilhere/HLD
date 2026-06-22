import { useState, useEffect, useRef, useCallback } from 'react';
import { Search, Clock, TrendingUp, ChevronRight } from 'lucide-react';

interface Suggestion {
  q: string;
  c: number;
  score: number;
}

interface SuggestionResponse {
  q: string;
  ms: number;
  results: Suggestion[];
  source?: string;
}

function App() {
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [trending, setTrending] = useState<Suggestion[]>([]);
  const [isFocused, setIsFocused] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [searchResult, setSearchResult] = useState<{ message: string; query: string; ms?: number; source?: string } | null>(null);
  
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Fetch initial trending
    fetch('http://localhost:8000/suggest?q=')
      .then(res => res.json())
      .then((data: SuggestionResponse) => setTrending(data.results))
      .catch(console.error);
  }, []);

  const fetchSuggestions = useCallback(async (q: string) => {
    if (!q) {
      setSuggestions([]);
      setLoading(false);
      return;
    }
    try {
      const res = await fetch(`http://localhost:8000/suggest?q=${encodeURIComponent(q)}`);
      const data: SuggestionResponse = await res.json();
      setSuggestions(data.results);
      setSearchResult(prev => prev ? { ...prev, ms: data.ms, source: data.source } : prev);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const handler = setTimeout(() => {
      fetchSuggestions(query);
    }, 300);
    return () => clearTimeout(handler);
  }, [query, fetchSuggestions]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsFocused(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    const items = query ? suggestions : trending;
    
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(prev => (prev < items.length - 1 ? prev + 1 : prev));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(prev => (prev > 0 ? prev - 1 : -1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (selectedIndex >= 0 && items[selectedIndex]) {
        handleSearch(items[selectedIndex].q);
      } else if (query.trim()) {
        handleSearch(query);
      }
    } else if (e.key === 'Escape') {
      setIsFocused(false);
    }
  };

  const handleSearch = async (searchQuery: string) => {
    setQuery(searchQuery);
    setIsFocused(false);
    setSelectedIndex(-1);
    
    try {
      const res = await fetch('http://localhost:8000/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchQuery }),
      });
      const data = await res.json();
      setSearchResult({ message: data.message, query: searchQuery });
      
      // Update trending slightly later
      setTimeout(() => {
        fetch('http://localhost:8000/suggest?q=')
          .then(res => res.json())
          .then((data: SuggestionResponse) => setTrending(data.results));
      }, 6000); // 6 seconds to allow batch writer to flush
    } catch (err) {
      console.error(err);
    }
  };

  const showDropdown = isFocused && (query.trim() ? suggestions.length > 0 : trending.length > 0);

  return (
    <div className="min-h-screen flex flex-col items-center pt-32 px-4 bg-gradient-to-b from-slate-50 to-slate-100">
      <div className="w-full max-w-2xl relative" ref={containerRef}>
        <div className="text-center mb-8">
          <h1 className="text-4xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-indigo-600 mb-2">
            Antigravity Search
          </h1>
          <p className="text-slate-500">Lightning fast typeahead with Redis consistent hashing</p>
        </div>

        <div className="relative group">
          <div className={`absolute inset-0 bg-blue-500 rounded-2xl blur opacity-20 group-hover:opacity-30 transition-opacity duration-300 ${isFocused ? 'opacity-40 blur-md' : ''}`}></div>
          <div className="relative flex items-center w-full bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-transparent transition-all duration-200">
            <Search className="w-6 h-6 ml-4 text-slate-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setLoading(true);
                setIsFocused(true);
                setSelectedIndex(-1);
              }}
              onFocus={() => setIsFocused(true)}
              onKeyDown={handleKeyDown}
              className="w-full py-4 px-4 text-lg bg-transparent border-none outline-none text-slate-800 placeholder-slate-400"
              placeholder="Search anything..."
            />
            {loading && (
              <div className="mr-4 animate-spin rounded-full h-5 w-5 border-b-2 border-blue-500"></div>
            )}
          </div>
        </div>

        {showDropdown && (
          <div className="absolute w-full mt-2 bg-white rounded-2xl shadow-xl border border-slate-100 overflow-hidden z-50">
            {!query.trim() && trending.length > 0 && (
              <div className="px-4 py-3 bg-slate-50/80 border-b border-slate-100 flex items-center text-sm font-semibold text-slate-500">
                <TrendingUp className="w-4 h-4 mr-2 text-indigo-500" />
                Trending Searches
              </div>
            )}
            <ul className="max-h-[400px] overflow-y-auto py-2">
              {(query ? suggestions : trending).map((item, index) => (
                <li
                  key={item.q}
                  className={`px-4 py-3 flex items-center justify-between cursor-pointer transition-colors ${
                    index === selectedIndex ? 'bg-blue-50' : 'hover:bg-slate-50'
                  }`}
                  onMouseEnter={() => setSelectedIndex(index)}
                  onClick={() => handleSearch(item.q)}
                >
                  <div className="flex items-center">
                    {!query ? (
                      <Clock className="w-4 h-4 mr-3 text-slate-400" />
                    ) : (
                      <Search className="w-4 h-4 mr-3 text-slate-400" />
                    )}
                    <span className={`text-base ${index === selectedIndex ? 'text-blue-700' : 'text-slate-700'}`}>
                      {item.q}
                    </span>
                  </div>
                  <div className="flex items-center text-xs text-slate-400">
                    <span className="bg-slate-100 px-2 py-1 rounded-md">{item.c.toLocaleString()}</span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {searchResult && (
        <div className="mt-12 w-full max-w-2xl animate-fade-in-up">
          <div className="bg-white rounded-2xl p-6 shadow-sm border border-slate-200">
            <h3 className="text-lg font-semibold text-slate-800 mb-2 flex items-center">
              <ChevronRight className="w-5 h-5 text-blue-500 mr-1" />
              Search Results
            </h3>
            <div className="pl-6 text-slate-600">
              <p className="mb-4">
                You searched for <strong className="text-slate-900 bg-yellow-100 px-1 rounded">"{searchResult.query}"</strong>.
              </p>
              <div className="inline-flex items-center space-x-2 px-3 py-2 bg-green-50 text-green-700 rounded-lg text-sm font-medium">
                <div className="w-2 h-2 rounded-full bg-green-500"></div>
                <span>Server response: {searchResult.message}</span>
              </div>
              {searchResult.ms !== undefined && (
                <div className="mt-4 flex items-center text-xs text-slate-500 space-x-4">
                  <span className="flex items-center">
                    <span className="w-1.5 h-1.5 rounded-full bg-slate-400 mr-1.5"></span>
                    Latency: {searchResult.ms}ms
                  </span>
                  <span className="flex items-center">
                    <span className="w-1.5 h-1.5 rounded-full bg-slate-400 mr-1.5"></span>
                    Source: <span className="uppercase ml-1 font-semibold">{searchResult.source || 'trie'}</span>
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;

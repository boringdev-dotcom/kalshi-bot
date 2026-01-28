import { useState, useEffect } from 'react';
import { 
  FlaskConical, 
  Play, 
  Loader2, 
  CheckCircle, 
  XCircle, 
  ChevronDown, 
  ChevronRight,
  RefreshCw,
  Clock,
  FileText
} from 'lucide-react';
import { clsx } from 'clsx';
import { fetchResearchGames, startResearchJob, getResearchJob, type ResearchGame, type ResearchJob } from '../api';

type PromptVersion = 'v1' | 'v2' | 'v3';

interface GroupedGames {
  [sport: string]: {
    [league: string]: ResearchGame[];
  };
}

export function ResearchPage() {
  const [games, setGames] = useState<ResearchGame[]>([]);
  const [groupedGames, setGroupedGames] = useState<GroupedGames>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [expandedSports, setExpandedSports] = useState<Set<string>>(new Set(['basketball', 'soccer']));
  const [expandedLeagues, setExpandedLeagues] = useState<Set<string>>(new Set());
  
  const [selectedGame, setSelectedGame] = useState<ResearchGame | null>(null);
  const [promptVersion, setPromptVersion] = useState<PromptVersion>('v1');
  
  const [activeJob, setActiveJob] = useState<ResearchJob | null>(null);
  
  // Load games
  useEffect(() => {
    loadGames();
  }, []);
  
  const loadGames = async () => {
    try {
      setIsLoading(true);
      setError(null);
      const response = await fetchResearchGames();
      setGames(response.games);
      
      // Group games by sport and league
      const grouped: GroupedGames = {};
      for (const game of response.games) {
        if (!grouped[game.sport]) {
          grouped[game.sport] = {};
        }
        if (!grouped[game.sport][game.league]) {
          grouped[game.sport][game.league] = [];
        }
        grouped[game.sport][game.league].push(game);
      }
      setGroupedGames(grouped);
      
      // Auto-expand leagues with games
      const leaguesWithGames = new Set<string>();
      for (const sport of Object.keys(grouped)) {
        for (const league of Object.keys(grouped[sport])) {
          leaguesWithGames.add(`${sport}-${league}`);
        }
      }
      setExpandedLeagues(leaguesWithGames);
      
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load games');
    } finally {
      setIsLoading(false);
    }
  };
  
  // Poll job status
  useEffect(() => {
    if (activeJob && (activeJob.status === 'pending' || activeJob.status === 'running')) {
      const interval = window.setInterval(async () => {
        try {
          const job = await getResearchJob(activeJob.job_id);
          setActiveJob(job);
          
          if (job.status === 'completed' || job.status === 'failed') {
            window.clearInterval(interval);
          }
        } catch (e) {
          console.error('Failed to poll job status:', e);
        }
      }, 3000);
      
      return () => {
        window.clearInterval(interval);
      };
    }
  }, [activeJob?.job_id, activeJob?.status]);
  
  const handleStartResearch = async () => {
    if (!selectedGame) return;
    
    try {
      const response = await startResearchJob({
        sport: selectedGame.sport,
        match_id: selectedGame.match_id,
        prompt_version: promptVersion,
      });
      
      setActiveJob({
        job_id: response.job_id,
        status: response.status as ResearchJob['status'],
        created_at: response.created_at,
        sport: selectedGame.sport,
        match_id: selectedGame.match_id,
      });
      
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start research job');
    }
  };
  
  const toggleSport = (sport: string) => {
    setExpandedSports(prev => {
      const next = new Set(prev);
      if (next.has(sport)) {
        next.delete(sport);
      } else {
        next.add(sport);
      }
      return next;
    });
  };
  
  const toggleLeague = (key: string) => {
    setExpandedLeagues(prev => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };
  
  const sportEmoji: Record<string, string> = {
    basketball: '🏀',
    soccer: '⚽',
    cricket: '🏏',
  };
  
  const leagueEmoji: Record<string, string> = {
    nba: '🏀',
    la_liga: '🇪🇸',
    premier_league: '🏴󠁧󠁢󠁥󠁮󠁧󠁿',
    mls: '🇺🇸',
    ucl: '🏆',
    bundesliga: '🇩🇪',
    t20_international: '🏏',
    ipl: '🇮🇳',
  };

  return (
    <div className="h-full flex overflow-hidden">
      {/* Left Panel - Game Selection */}
      <div className="w-80 flex-none border-r border-border-subtle flex flex-col bg-bg-primary">
        <div className="p-4 border-b border-border-subtle">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FlaskConical className="w-5 h-5 text-accent-blue" />
              <h2 className="text-lg font-semibold text-text-primary">Research</h2>
            </div>
            <button
              onClick={loadGames}
              disabled={isLoading}
              className="p-1.5 rounded hover:bg-bg-secondary transition-colors text-text-muted hover:text-text-primary"
            >
              <RefreshCw className={clsx('w-4 h-4', isLoading && 'animate-spin')} />
            </button>
          </div>
          <p className="text-sm text-text-muted mt-1">
            Select a game for LLM Council analysis
          </p>
        </div>
        
        {/* Game List */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="p-4 flex items-center justify-center">
              <Loader2 className="w-6 h-6 animate-spin text-text-muted" />
            </div>
          ) : error ? (
            <div className="p-4 text-accent-red text-sm">{error}</div>
          ) : games.length === 0 ? (
            <div className="p-4 text-text-muted text-sm">No games available</div>
          ) : (
            <div className="p-2">
              {Object.entries(groupedGames).map(([sport, leagues]) => (
                <div key={sport} className="mb-2">
                  {/* Sport Header */}
                  <button
                    onClick={() => toggleSport(sport)}
                    className="w-full flex items-center gap-2 px-2 py-1.5 rounded hover:bg-bg-secondary transition-colors"
                  >
                    {expandedSports.has(sport) ? (
                      <ChevronDown className="w-4 h-4 text-text-muted" />
                    ) : (
                      <ChevronRight className="w-4 h-4 text-text-muted" />
                    )}
                    <span className="text-lg">{sportEmoji[sport] || '🎯'}</span>
                    <span className="font-medium text-text-primary capitalize">{sport}</span>
                    <span className="text-xs text-text-muted ml-auto">
                      {Object.values(leagues).flat().length} games
                    </span>
                  </button>
                  
                  {/* Leagues */}
                  {expandedSports.has(sport) && (
                    <div className="ml-4">
                      {Object.entries(leagues).map(([league, leagueGames]) => {
                        const leagueKey = `${sport}-${league}`;
                        return (
                          <div key={league} className="mb-1">
                            {/* League Header */}
                            <button
                              onClick={() => toggleLeague(leagueKey)}
                              className="w-full flex items-center gap-2 px-2 py-1 rounded hover:bg-bg-secondary transition-colors text-sm"
                            >
                              {expandedLeagues.has(leagueKey) ? (
                                <ChevronDown className="w-3 h-3 text-text-muted" />
                              ) : (
                                <ChevronRight className="w-3 h-3 text-text-muted" />
                              )}
                              <span>{leagueEmoji[league] || '🏟️'}</span>
                              <span className="text-text-secondary">
                                {leagueGames[0]?.league_display || league}
                              </span>
                              <span className="text-xs text-text-muted ml-auto">
                                {leagueGames.length}
                              </span>
                            </button>
                            
                            {/* Games */}
                            {expandedLeagues.has(leagueKey) && (
                              <div className="ml-4">
                                {leagueGames.map((game) => (
                                  <button
                                    key={game.match_id}
                                    onClick={() => setSelectedGame(game)}
                                    className={clsx(
                                      'w-full text-left px-2 py-1.5 rounded text-sm transition-colors',
                                      selectedGame?.match_id === game.match_id
                                        ? 'bg-accent-blue/15 text-accent-blue'
                                        : 'hover:bg-bg-secondary text-text-secondary hover:text-text-primary'
                                    )}
                                  >
                                    <div className="truncate">{game.title}</div>
                                    <div className="text-xs text-text-muted">
                                      {game.market_count} markets
                                    </div>
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      
      {/* Main Content Area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {selectedGame ? (
          <>
            {/* Game Info & Controls */}
            <div className="flex-none p-4 border-b border-border-subtle">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xl">{sportEmoji[selectedGame.sport]}</span>
                    <h3 className="text-lg font-semibold text-text-primary">
                      {selectedGame.title}
                    </h3>
                  </div>
                  <div className="flex items-center gap-3 mt-1 text-sm text-text-muted">
                    <span>{leagueEmoji[selectedGame.league]} {selectedGame.league_display}</span>
                    <span>•</span>
                    <span>{selectedGame.market_count} markets</span>
                    {selectedGame.close_time && (
                      <>
                        <span>•</span>
                        <span className="flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {new Date(selectedGame.close_time).toLocaleString()}
                        </span>
                      </>
                    )}
                  </div>
                </div>
                
                {/* Research Controls */}
                <div className="flex items-center gap-3">
                  <select
                    value={promptVersion}
                    onChange={(e) => setPromptVersion(e.target.value as PromptVersion)}
                    className="px-3 py-1.5 rounded-md bg-bg-secondary border border-border-subtle text-sm text-text-primary"
                    disabled={activeJob?.status === 'running' || activeJob?.status === 'pending'}
                  >
                    <option value="v1">Prompt V1 (Original)</option>
                    <option value="v2">Prompt V2 (Multi-stage)</option>
                    {selectedGame.sport === 'soccer' && (
                      <option value="v3">Prompt V3 (UCL)</option>
                    )}
                  </select>
                  
                  <button
                    onClick={handleStartResearch}
                    disabled={activeJob?.status === 'running' || activeJob?.status === 'pending'}
                    className={clsx(
                      'flex items-center gap-2 px-4 py-1.5 rounded-md font-medium transition-colors',
                      activeJob?.status === 'running' || activeJob?.status === 'pending'
                        ? 'bg-bg-secondary text-text-muted cursor-not-allowed'
                        : 'bg-accent-blue text-white hover:bg-accent-blue/90'
                    )}
                  >
                    {activeJob?.status === 'running' || activeJob?.status === 'pending' ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Running...
                      </>
                    ) : (
                      <>
                        <Play className="w-4 h-4" />
                        Run Analysis
                      </>
                    )}
                  </button>
                </div>
              </div>
              
              {/* Job Status */}
              {activeJob && (
                <div className={clsx(
                  'mt-3 p-3 rounded-lg flex items-center gap-3',
                  activeJob.status === 'completed' && 'bg-accent-green/10 border border-accent-green/30',
                  activeJob.status === 'failed' && 'bg-accent-red/10 border border-accent-red/30',
                  (activeJob.status === 'running' || activeJob.status === 'pending') && 'bg-accent-blue/10 border border-accent-blue/30'
                )}>
                  {activeJob.status === 'completed' && (
                    <CheckCircle className="w-5 h-5 text-accent-green" />
                  )}
                  {activeJob.status === 'failed' && (
                    <XCircle className="w-5 h-5 text-accent-red" />
                  )}
                  {(activeJob.status === 'running' || activeJob.status === 'pending') && (
                    <Loader2 className="w-5 h-5 text-accent-blue animate-spin" />
                  )}
                  <div className="flex-1">
                    <div className="font-medium text-text-primary capitalize">
                      {activeJob.status === 'pending' && 'Starting analysis...'}
                      {activeJob.status === 'running' && 'Analysis in progress...'}
                      {activeJob.status === 'completed' && 'Analysis complete!'}
                      {activeJob.status === 'failed' && 'Analysis failed'}
                    </div>
                    <div className="text-sm text-text-muted">
                      {activeJob.status === 'running' && 'This may take 2-5 minutes'}
                      {activeJob.status === 'completed' && activeJob.completed_at && (
                        `Completed at ${new Date(activeJob.completed_at).toLocaleTimeString()}`
                      )}
                      {activeJob.status === 'failed' && activeJob.error}
                    </div>
                  </div>
                </div>
              )}
            </div>
            
            {/* Results Area */}
            <div className="flex-1 overflow-y-auto p-4">
              {activeJob?.status === 'completed' && activeJob.result ? (
                <ResearchResults result={activeJob.result} />
              ) : activeJob?.status === 'running' || activeJob?.status === 'pending' ? (
                <div className="h-full flex items-center justify-center">
                  <div className="text-center">
                    <Loader2 className="w-12 h-12 text-accent-blue animate-spin mx-auto mb-4" />
                    <p className="text-text-primary font-medium">Running LLM Council Analysis</p>
                    <p className="text-text-muted text-sm mt-2">
                      Stage 1: Research with Gemini + Google Search grounding<br />
                      Stage 2: Analysis by multiple LLMs<br />
                      Stage 3: Peer review<br />
                      Stage 4: Chairman synthesis
                    </p>
                  </div>
                </div>
              ) : (
                <div className="h-full flex items-center justify-center text-text-muted">
                  <div className="text-center">
                    <FlaskConical className="w-12 h-12 mx-auto mb-4 opacity-50" />
                    <p>Click "Run Analysis" to start LLM Council research</p>
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="h-full flex items-center justify-center text-text-muted">
            <div className="text-center">
              <FlaskConical className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>Select a game from the left panel to begin research</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

interface ResearchResultsProps {
  result: {
    title: string;
    research: string;
    analyses: Record<string, string>;
    reviews: Record<string, string>;
    final_recommendation: string;
    metadata: Record<string, any>;
  };
}

function ResearchResults({ result }: ResearchResultsProps) {
  const [activeTab, setActiveTab] = useState<'recommendation' | 'research' | 'analyses' | 'reviews'>('recommendation');
  
  const tabs = [
    { id: 'recommendation' as const, label: 'Final Recommendation', icon: FileText },
    { id: 'research' as const, label: 'Research', icon: FlaskConical },
    { id: 'analyses' as const, label: 'Analyses', icon: FileText },
    { id: 'reviews' as const, label: 'Reviews', icon: FileText },
  ];
  
  return (
    <div className="h-full flex flex-col">
      {/* Tabs */}
      <div className="flex-none flex gap-1 mb-4 border-b border-border-subtle pb-2">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={clsx(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
              activeTab === tab.id
                ? 'bg-accent-blue/15 text-accent-blue'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-secondary'
            )}
          >
            <tab.icon className="w-4 h-4" />
            {tab.label}
          </button>
        ))}
      </div>
      
      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === 'recommendation' && (
          <div className="glass-panel p-4">
            <h3 className="text-lg font-semibold text-text-primary mb-3">
              🎯 Final Recommendation
            </h3>
            <div className="prose prose-invert max-w-none">
              <pre className="whitespace-pre-wrap text-sm text-text-secondary font-sans">
                {result.final_recommendation}
              </pre>
            </div>
          </div>
        )}
        
        {activeTab === 'research' && (
          <div className="glass-panel p-4">
            <h3 className="text-lg font-semibold text-text-primary mb-3">
              📊 Research Findings
            </h3>
            <div className="text-xs text-text-muted mb-3">
              Model: {result.metadata?.research_model || 'Gemini'} (Google Search grounding)
            </div>
            <div className="prose prose-invert max-w-none">
              <pre className="whitespace-pre-wrap text-sm text-text-secondary font-sans">
                {result.research}
              </pre>
            </div>
          </div>
        )}
        
        {activeTab === 'analyses' && (
          <div className="space-y-4">
            {Object.entries(result.analyses).map(([model, analysis]) => (
              <div key={model} className="glass-panel p-4">
                <h3 className="text-lg font-semibold text-text-primary mb-3">
                  🤖 {model.split('/').pop() || model}
                </h3>
                <div className="prose prose-invert max-w-none">
                  <pre className="whitespace-pre-wrap text-sm text-text-secondary font-sans">
                    {analysis}
                  </pre>
                </div>
              </div>
            ))}
          </div>
        )}
        
        {activeTab === 'reviews' && (
          <div className="space-y-4">
            {Object.entries(result.reviews).map(([model, review]) => (
              <div key={model} className="glass-panel p-4">
                <h3 className="text-lg font-semibold text-text-primary mb-3">
                  📝 Review by {model.split('/').pop() || model}
                </h3>
                <div className="prose prose-invert max-w-none">
                  <pre className="whitespace-pre-wrap text-sm text-text-secondary font-sans">
                    {review}
                  </pre>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      
      {/* Metadata */}
      <div className="flex-none mt-4 pt-3 border-t border-border-subtle">
        <div className="flex flex-wrap gap-4 text-xs text-text-muted">
          {result.metadata?.council_models && (
            <span>Council: {result.metadata.council_models.join(', ')}</span>
          )}
          {result.metadata?.chairman_model && (
            <span>Chairman: {result.metadata.chairman_model}</span>
          )}
          {result.metadata?.prompt_version && (
            <span>Prompt: {result.metadata.prompt_version.toUpperCase()}</span>
          )}
        </div>
      </div>
    </div>
  );
}

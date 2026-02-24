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
  FileText,
  Layers,
  X,
  Plus
} from 'lucide-react';
import { clsx } from 'clsx';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { 
  fetchResearchGames, 
  startResearchJob, 
  startComboResearchJob,
  getResearchJob, 
  type ResearchGame, 
  type ResearchJob 
} from '../api';

// Markdown renderer component
function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="markdown-content">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

type PromptVersion = 'v1' | 'v2' | 'v3';
type AnalysisMode = 'single' | 'combo';

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
  
  // Multi-selection state
  const [selectedGames, setSelectedGames] = useState<ResearchGame[]>([]);
  const [analysisMode, setAnalysisMode] = useState<AnalysisMode>('combo');
  const [promptVersion, setPromptVersion] = useState<PromptVersion>('v2');
  const [useCombinedAnalysis, setUseCombinedAnalysis] = useState(true);
  
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
  
  const handleToggleGame = (game: ResearchGame) => {
    setSelectedGames(prev => {
      const isSelected = prev.some(g => g.match_id === game.match_id);
      if (isSelected) {
        return prev.filter(g => g.match_id !== game.match_id);
      } else {
        // For combo mode, allow multiple; for single, replace
        if (analysisMode === 'single') {
          return [game];
        }
        return [...prev, game];
      }
    });
  };
  
  const handleRemoveGame = (matchId: string) => {
    setSelectedGames(prev => prev.filter(g => g.match_id !== matchId));
  };
  
  const handleStartResearch = async () => {
    if (selectedGames.length === 0) return;
    
    try {
      setError(null);
      
      if (analysisMode === 'combo' && selectedGames.length >= 2) {
        // Combo research
        const response = await startComboResearchJob({
          sport: selectedGames[0].sport,
          match_ids: selectedGames.map(g => g.match_id),
          use_combined_analysis: useCombinedAnalysis,
        });
        
        setActiveJob({
          job_id: response.job_id,
          status: response.status as ResearchJob['status'],
          created_at: response.created_at,
          sport: selectedGames[0].sport,
          match_id: selectedGames.map(g => g.match_id).join(','),
        });
      } else {
        // Single game research
        const game = selectedGames[0];
        const response = await startResearchJob({
          sport: game.sport,
          match_id: game.match_id,
          prompt_version: promptVersion,
        });
        
        setActiveJob({
          job_id: response.job_id,
          status: response.status as ResearchJob['status'],
          created_at: response.created_at,
          sport: game.sport,
          match_id: game.match_id,
        });
      }
      
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
  
  const isGameSelected = (game: ResearchGame) => 
    selectedGames.some(g => g.match_id === game.match_id);
  
  const canRunAnalysis = analysisMode === 'combo' 
    ? selectedGames.length >= 2 
    : selectedGames.length === 1;

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
          
          {/* Mode Toggle */}
          <div className="flex gap-1 mt-3 p-1 bg-bg-secondary rounded-lg">
            <button
              onClick={() => {
                setAnalysisMode('combo');
                if (selectedGames.length === 1) {
                  // Keep selection for combo
                }
              }}
              className={clsx(
                'flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium transition-colors',
                analysisMode === 'combo'
                  ? 'bg-accent-blue text-white'
                  : 'text-text-secondary hover:text-text-primary'
              )}
            >
              <Layers className="w-4 h-4" />
              Combo
            </button>
            <button
              onClick={() => {
                setAnalysisMode('single');
                if (selectedGames.length > 1) {
                  setSelectedGames([selectedGames[0]]);
                }
              }}
              className={clsx(
                'flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium transition-colors',
                analysisMode === 'single'
                  ? 'bg-accent-blue text-white'
                  : 'text-text-secondary hover:text-text-primary'
              )}
            >
              <FileText className="w-4 h-4" />
              Single
            </button>
          </div>
          
          <p className="text-xs text-text-muted mt-2">
            {analysisMode === 'combo' 
              ? 'Select 2-6 games for combo betting analysis'
              : 'Select a game for detailed analysis'}
          </p>
        </div>
        
        {/* Selected Games */}
        {selectedGames.length > 0 && (
          <div className="p-3 border-b border-border-subtle bg-bg-secondary/50">
            <div className="text-xs font-medium text-text-muted mb-2">
              Selected ({selectedGames.length})
            </div>
            <div className="space-y-1">
              {selectedGames.map((game) => (
                <div
                  key={game.match_id}
                  className="flex items-center justify-between px-2 py-1.5 bg-accent-blue/10 rounded text-sm"
                >
                  <span className="text-text-primary truncate flex-1">
                    {sportEmoji[game.sport]} {game.title}
                  </span>
                  <button
                    onClick={() => handleRemoveGame(game.match_id)}
                    className="p-0.5 hover:bg-bg-secondary rounded transition-colors text-text-muted hover:text-text-primary"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
        
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
                                {leagueGames.map((game) => {
                                  const selected = isGameSelected(game);
                                  return (
                                    <button
                                      key={game.match_id}
                                      onClick={() => handleToggleGame(game)}
                                      className={clsx(
                                        'w-full text-left px-2 py-1.5 rounded text-sm transition-colors flex items-center gap-2',
                                        selected
                                          ? 'bg-accent-blue/15 text-accent-blue'
                                          : 'hover:bg-bg-secondary text-text-secondary hover:text-text-primary'
                                      )}
                                    >
                                      <div className={clsx(
                                        'w-4 h-4 rounded border-2 flex items-center justify-center flex-shrink-0',
                                        selected 
                                          ? 'bg-accent-blue border-accent-blue' 
                                          : 'border-border-subtle'
                                      )}>
                                        {selected && <Plus className="w-3 h-3 text-white rotate-45" />}
                                      </div>
                                      <div className="flex-1 min-w-0">
                                        <div className="truncate">{game.title}</div>
                                        <div className="text-xs text-text-muted">
                                          {game.market_count} markets
                                        </div>
                                      </div>
                                    </button>
                                  );
                                })}
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
        {/* Controls Header */}
        <div className="flex-none p-4 border-b border-border-subtle">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-semibold text-text-primary">
                {analysisMode === 'combo' ? '🎯 Combo Analysis' : '📊 Single Game Analysis'}
              </h3>
              <p className="text-sm text-text-muted">
                {analysisMode === 'combo' 
                  ? `${selectedGames.length} game${selectedGames.length !== 1 ? 's' : ''} selected`
                  : selectedGames.length === 1 
                    ? selectedGames[0].title 
                    : 'No game selected'}
              </p>
            </div>
            
            {/* Analysis Controls */}
            <div className="flex items-center gap-3">
              {analysisMode === 'single' && (
                <select
                  value={promptVersion}
                  onChange={(e) => setPromptVersion(e.target.value as PromptVersion)}
                  className="px-3 py-1.5 rounded-md bg-bg-secondary border border-border-subtle text-sm text-text-primary"
                  disabled={activeJob?.status === 'running' || activeJob?.status === 'pending'}
                >
                  <option value="v1">Prompt V1 (Original)</option>
                  <option value="v2">Prompt V2 (Multi-stage)</option>
                  {selectedGames[0]?.sport === 'soccer' && (
                    <option value="v3">Prompt V3 (UCL)</option>
                  )}
                </select>
              )}
              
              {analysisMode === 'combo' && (
                <label className="flex items-center gap-2 text-sm text-text-secondary">
                  <input
                    type="checkbox"
                    checked={useCombinedAnalysis}
                    onChange={(e) => setUseCombinedAnalysis(e.target.checked)}
                    className="rounded border-border-subtle"
                    disabled={activeJob?.status === 'running' || activeJob?.status === 'pending'}
                  />
                  Include spreads
                </label>
              )}
              
              <button
                onClick={handleStartResearch}
                disabled={!canRunAnalysis || activeJob?.status === 'running' || activeJob?.status === 'pending'}
                className={clsx(
                  'flex items-center gap-2 px-4 py-1.5 rounded-md font-medium transition-colors',
                  !canRunAnalysis || activeJob?.status === 'running' || activeJob?.status === 'pending'
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
                    {analysisMode === 'combo' ? 'Run Combo Analysis' : 'Run Analysis'}
                  </>
                )}
              </button>
            </div>
          </div>
          
          {/* Job Status */}
          {activeJob && (
            <div className={clsx(
              'mt-3 p-3 rounded-lg flex items-start gap-3',
              activeJob.status === 'completed' && 'bg-accent-green/10 border border-accent-green/30',
              activeJob.status === 'failed' && 'bg-accent-red/10 border border-accent-red/30',
              (activeJob.status === 'running' || activeJob.status === 'pending') && 'bg-accent-blue/10 border border-accent-blue/30'
            )}>
              {activeJob.status === 'completed' && (
                <CheckCircle className="w-5 h-5 text-accent-green flex-shrink-0 mt-0.5" />
              )}
              {activeJob.status === 'failed' && (
                <XCircle className="w-5 h-5 text-accent-red flex-shrink-0 mt-0.5" />
              )}
              {(activeJob.status === 'running' || activeJob.status === 'pending') && (
                <Loader2 className="w-5 h-5 text-accent-blue animate-spin flex-shrink-0 mt-0.5" />
              )}
              <div className="flex-1 min-w-0">
                <div className="font-medium text-text-primary capitalize">
                  {activeJob.status === 'pending' && 'Starting analysis...'}
                  {activeJob.status === 'running' && 'Analysis in progress...'}
                  {activeJob.status === 'completed' && 'Analysis complete!'}
                  {activeJob.status === 'failed' && 'Analysis failed'}
                </div>
                <div className="text-sm text-text-muted">
                  {activeJob.status === 'running' && 'This may take 5-15 minutes for combo analysis'}
                  {activeJob.status === 'completed' && activeJob.completed_at && (
                    `Completed at ${new Date(activeJob.completed_at).toLocaleTimeString()}`
                  )}
                  {activeJob.status === 'failed' && activeJob.error}
                </div>
                {/* Progress messages */}
                {(activeJob as any).progress?.length > 0 && (
                  <div className="mt-2 text-xs text-text-muted max-h-20 overflow-y-auto">
                    {((activeJob as any).progress as Array<{message: string; timestamp: string}>)
                      .slice(-5)
                      .map((p, i) => (
                        <div key={i} className="truncate">{p.message}</div>
                      ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
        
        {/* Results Area */}
        <div className="flex-1 overflow-y-auto p-4">
          {activeJob?.status === 'completed' && activeJob.result ? (
            <ResearchResults result={activeJob.result} isCombo={analysisMode === 'combo'} />
          ) : activeJob?.status === 'running' || activeJob?.status === 'pending' ? (
            <div className="h-full flex items-center justify-center">
              <div className="text-center">
                <Loader2 className="w-12 h-12 text-accent-blue animate-spin mx-auto mb-4" />
                <p className="text-text-primary font-medium">
                  {analysisMode === 'combo' ? 'Running Deep Research Combo Analysis' : 'Running LLM Council Analysis'}
                </p>
                <p className="text-text-muted text-sm mt-2 max-w-md">
                  {analysisMode === 'combo' ? (
                    <>
                      Deep Research is performing web research + market analysis<br />
                      Then generating combo recommendations with edge estimates
                    </>
                  ) : (
                    <>
                      Stage 1: Research with Gemini + Google Search grounding<br />
                      Stage 2: Analysis by multiple LLMs<br />
                      Stage 3: Peer review<br />
                      Stage 4: Chairman synthesis
                    </>
                  )}
                </p>
              </div>
            </div>
          ) : (
            <div className="h-full flex items-center justify-center text-text-muted">
              <div className="text-center">
                <FlaskConical className="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p>
                  {analysisMode === 'combo' 
                    ? 'Select 2-6 games and click "Run Combo Analysis"'
                    : 'Select a game and click "Run Analysis"'}
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

interface ResearchResultsProps {
  result: {
    title?: string;
    games?: string[];
    research: string;
    analyses: Record<string, string>;
    reviews: Record<string, string>;
    final_recommendation: string;
    metadata: Record<string, any>;
  };
  isCombo?: boolean;
}

function ResearchResults({ result, isCombo }: ResearchResultsProps) {
  const [activeTab, setActiveTab] = useState<'recommendation' | 'research' | 'analyses' | 'reviews'>('recommendation');
  
  const tabs = [
    { id: 'recommendation' as const, label: isCombo ? 'Combo Picks' : 'Final Recommendation', icon: FileText },
    { id: 'research' as const, label: 'Research', icon: FlaskConical },
    ...(Object.keys(result.analyses).length > 0 ? [
      { id: 'analyses' as const, label: 'Analyses', icon: FileText },
    ] : []),
    ...(Object.keys(result.reviews).length > 0 ? [
      { id: 'reviews' as const, label: 'Reviews', icon: FileText },
    ] : []),
  ];
  
  return (
    <div className="h-full flex flex-col">
      {/* Games header for combo */}
      {isCombo && result.games && result.games.length > 0 && (
        <div className="flex-none mb-4 p-3 bg-bg-secondary rounded-lg">
          <div className="text-xs font-medium text-text-muted mb-2">Games in Combo</div>
          <div className="flex flex-wrap gap-2">
            {result.games.map((game, i) => (
              <span key={i} className="px-2 py-1 bg-accent-blue/10 text-accent-blue text-sm rounded">
                {game}
              </span>
            ))}
          </div>
        </div>
      )}
      
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
              {isCombo ? '🎯 Combo Betting Recommendations' : '🎯 Final Recommendation'}
            </h3>
            <MarkdownContent content={result.final_recommendation} />
          </div>
        )}
        
        {activeTab === 'research' && (
          <div className="glass-panel p-4">
            <h3 className="text-lg font-semibold text-text-primary mb-3">
              📊 Research Findings
            </h3>
            <div className="text-xs text-text-muted mb-3">
              Model: {result.metadata?.research_model || result.metadata?.analysis_model || 'Gemini'} (Google Search grounding)
            </div>
            <MarkdownContent content={result.research} />
          </div>
        )}
        
        {activeTab === 'analyses' && Object.keys(result.analyses).length > 0 && (
          <div className="space-y-4">
            {Object.entries(result.analyses).map(([model, analysis]) => (
              <div key={model} className="glass-panel p-4">
                <h3 className="text-lg font-semibold text-text-primary mb-3">
                  🤖 {model.split('/').pop() || model}
                </h3>
                <MarkdownContent content={analysis} />
              </div>
            ))}
          </div>
        )}
        
        {activeTab === 'reviews' && Object.keys(result.reviews).length > 0 && (
          <div className="space-y-4">
            {Object.entries(result.reviews).map(([model, review]) => (
              <div key={model} className="glass-panel p-4">
                <h3 className="text-lg font-semibold text-text-primary mb-3">
                  📝 Review by {model.split('/').pop() || model}
                </h3>
                <MarkdownContent content={review} />
              </div>
            ))}
          </div>
        )}
      </div>
      
      {/* Metadata */}
      <div className="flex-none mt-4 pt-3 border-t border-border-subtle">
        <div className="flex flex-wrap gap-4 text-xs text-text-muted">
          {result.metadata?.mode && (
            <span>Mode: {result.metadata.mode}</span>
          )}
          {result.metadata?.analysis_type && (
            <span>Analysis: {result.metadata.analysis_type}</span>
          )}
          {result.metadata?.council_models?.length > 0 && (
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

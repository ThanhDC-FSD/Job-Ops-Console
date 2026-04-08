import { useEffect, useMemo, useState } from 'react'
import { api } from './api/client'
import { useRef } from 'react'
import { createLogger } from './utils/logger'
import { geoMercator, geoPath } from 'd3-geo'
import { feature as topojsonFeature } from 'topojson-client'
import worldAtlas from 'world-atlas/countries-110m.json'

const TIMEZONE = 'Asia/Ho_Chi_Minh'
let appDidBootstrap = false
const APPLIED_TREND_VIEW_KEY = 'jobOps.appliedTrend.view'
const JOBS_DENSITY_MAP_VIEW_KEY = 'jobOps.jobsDensityMap.view'
const UI_STATE_TTL_MS = 30 * 24 * 60 * 60 * 1000
const ACTIVE_TAB_STATE_KEY = 'jobOps.ui.activeTab'
const DASHBOARD_PAGINATION_KEY = 'jobOps.ui.dashboard.pagination'
const JOBS_STATE_KEY = 'jobOps.ui.jobs.state'
const APPLIED_JOBS_STATE_KEY = 'jobOps.ui.appliedJobs.state'
const ANALYTICS_STATE_KEY = 'jobOps.ui.analytics.state'
const AUTOMATION_STATE_KEY = 'jobOps.ui.automation.state'
const applyCvLogger = createLogger('FE.ApplyCV')
const learningQuizLogger = createLogger('FE.LearningQuiz')

function pickLang(en, vi, lang = 'en') {
  if (lang === 'vi') {
    return vi || en || ''
  }
  return en || vi || ''
}

function readSessionJson(key, fallback) {
  if (typeof window === 'undefined') return fallback
  try {
    const raw = window.sessionStorage.getItem(key)
    if (!raw) return fallback
    return JSON.parse(raw)
  } catch {
    return fallback
  }
}

function writeSessionJson(key, value) {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value))
  } catch {
  }
}

function readStoredState(key, fallback) {
  if (typeof window === 'undefined') return fallback
  try {
    const raw = window.sessionStorage.getItem(key) || window.localStorage.getItem(key)
    if (!raw) return fallback
    const parsed = JSON.parse(raw)
    const expiresAt = Number(parsed?.expiresAt || 0)
    if (!expiresAt || expiresAt < Date.now()) {
      window.sessionStorage.removeItem(key)
      window.localStorage.removeItem(key)
      return fallback
    }
    const value = parsed?.value ?? fallback
    writeStoredState(key, value)
    return value
  } catch {
    return fallback
  }
}

function writeStoredState(key, value) {
  if (typeof window === 'undefined') return
  try {
    const payload = JSON.stringify({
      value,
      expiresAt: Date.now() + UI_STATE_TTL_MS,
    })
    window.sessionStorage.setItem(key, payload)
    window.localStorage.setItem(key, payload)
  } catch {
  }
}

function encodeBase64Text(value) {
  if (!value) return ''
  if (typeof window === 'undefined' || typeof window.btoa !== 'function') return ''
  try {
    return window.btoa(unescape(encodeURIComponent(String(value || ''))))
  } catch {
    return ''
  }
}

function readFileTextInput(file) {
  if (!file) return Promise.resolve('')
  if (typeof file.text === 'function') {
    return file.text()
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = reject
    reader.readAsText(file, 'utf-8')
  })
}

function toIsoFromDateTimeLocal(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toISOString()
}

function toDateTimeLocalValue(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return ''
  const yyyy = parsed.getFullYear()
  const mm = String(parsed.getMonth() + 1).padStart(2, '0')
  const dd = String(parsed.getDate()).padStart(2, '0')
  const hh = String(parsed.getHours()).padStart(2, '0')
  const mi = String(parsed.getMinutes()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}T${hh}:${mi}`
}

function buildLogViewerUrl(path, options = {}) {
  if (typeof window === 'undefined') return ''
  const rawPath = String(path || '').trim()
  if (!rawPath) return ''
  const params = new URLSearchParams()
  params.set('view', 'log')
  params.set('path', rawPath)
  if (options.runId) params.set('run_id', String(options.runId))
  if (options.actionType) params.set('action', String(options.actionType))
  if (options.running) params.set('running', '1')
  return `${window.location.origin}${window.location.pathname}?${params.toString()}`
}

function openLogViewer(path, options = {}) {
  const url = buildLogViewerUrl(path, options)
  if (!url || typeof window === 'undefined') return
  window.open(url, '_blank', 'noopener,noreferrer')
}

const i18n = {
  en: {
    appTitle: 'Job Ops Console',
    backendHealth: 'Backend health',
    dashboard: 'Dashboard',
    jobs: 'Jobs',
    appliedJobsPage: 'Applied Jobs',
    analytics: 'Reposts Analytics',
    automation: 'Automation',
    learningQuiz: 'Learning Quiz',
    knowledgeTab: 'Knowledge',
    interviewQaTab: 'Interview Q&A',
    knowledgeHint: 'Review the key theory and explanations before taking the quiz.',
    topic: 'Topic',
    startQuiz: 'Start Quiz',
    submitQuiz: 'Submit Quiz',
    quizHistory: 'Quiz History',
    quizLanguage: 'Quiz language',
    explanation: 'Explanation',
    correctAnswer: 'Correct Answer',
    yourAnswer: 'Your Answer',
    score: 'Score',
    scheduleLearningEtl: 'Schedule Learning ETL',
    queue: 'Queue',
    nextRun: 'Next run',
    noQuizQuestions: 'No quiz questions available yet.',
    totalJobs: 'Total Jobs',
    appliedJobs: 'Applied Jobs',
    respondedJobs: 'Responded Jobs',
    cvReadyJobs: 'CV Ready Jobs',
    crawlRuns: 'Crawl Runs',
    recentRuns: 'Recent Runs',
    loadingDashboard: 'Loading dashboard...',
    filter: 'Filter',
    all: 'All',
    filtered: 'Filtered',
    applied: 'Applied',
    company: 'Company',
    searchPlaceholder: 'Search title/company',
    evaluateFit: 'Evaluate Fit',
    constraintMode: 'Constraint Mode',
    hard: 'Hard',
    medium: 'Medium',
    soft: 'Soft',
    evaluating: 'Evaluating...',
    loading: 'Loading...',
    country: 'Country',
    workModel: 'Work Model',
    employmentType: 'Employment Type',
    easyApply: 'Easy Apply',
    programLanguage: 'Program Language',
    languageFilter: 'Language',
    response: 'Response',
    fit: 'Fit',
    fitScore: 'Fit Score',
    fitReason: 'Fit Reason',
    yes: 'Yes',
    no: 'No',
    notEvaluated: 'not evaluated',
    firstSeen: 'First Seen',
    lastSeen: 'Last Seen',
    noJdText: 'No JD text',
    run: 'Run',
    minReposts: 'Min reposts',
    location: 'Location',
    reposts: 'Reposts',
    durationDays: 'Duration Days',
    first: 'First',
    last: 'Last',
    distinctPosts: 'Distinct Posts',
    manualActions: 'Manual Actions',
    runCrawlFiltered: 'Run Crawl Filtered',
    runCrawlApplied: 'Run Crawl Applied',
    runGenerateCv: 'Run Generate CV',
    runGenerateInterviewQa: 'Generate Interview Q&A',
    pauseRun: 'Pause',
    predictJobIds: 'Job IDs',
    predictJobIdsPlaceholder: 'e.g. 4381111111,4382222222',
    predictCvPath: 'CV path',
    predictJdText: 'JD text',
    predictJdFile: 'JD file',
    predictJdHint: 'Paste JD text or upload a JD file for ad-hoc predictions.',
    predictRecentDays: 'Recent days',
    predictMaxJobs: 'Max jobs',
    predictStartAt: 'Start job time',
    predictForce: 'Force run even when feature flag is off',
    shutdownWhenCompleted: 'Shut down when completed',
    learningEtlPipeline: 'Learning ETL',
    createSchedule: 'Create Schedule',
    create: 'Create',
    schedules: 'Schedules',
    editSchedule: 'Edit schedule',
    saveChanges: 'Save Changes',
    cancelEditSchedule: 'Cancel Edit',
    pauseSchedule: 'Pause schedule',
    resumeSchedule: 'Resume schedule',
    enabled: 'Enabled',
    cron: 'Cron',
    pipeline: 'Pipeline',
    threshold: 'Threshold',
    status: 'Status',
    startedGmt7: 'Started (GMT+7)',
    language: 'Language',
    automationSummary: 'Run Summary',
    successRuns: 'Success',
    failedRuns: 'Failed',
    lastRunGmt7: 'Last Run (GMT+7)',
    postedDate: 'LinkedIn Posted Date',
    applyDate: 'Apply Date',
    postedTimeText: 'Posted Text',
    page: 'Page',
    prev: 'Prev',
    next: 'Next',
    pageSize: 'Page size',
    sortPostedDesc: 'Posted date newest',
    sortPostedAsc: 'Posted date oldest',
    sortDesc: 'Desc',
    sortAsc: 'Asc',
    fitSort: 'Fit sort',
    sortSeenDesc: 'Seen date newest',
    sortSeenAsc: 'Seen date oldest',
    postedWithinDays: 'Posted within (days)',
    postedWindow: 'Posted window',
    last1Day: 'Last 1 day',
    last1Week: 'Last 1 week',
    last1Month: 'Last 1 month',
    customDays: 'Custom days',
    estimatedFromText: 'estimated from posted text',
    scheduleName: 'Schedule name',
    scheduleType: 'Pipeline type',
    frequency: 'Frequency',
    everyHours: 'Every N hours',
    daily: 'Daily',
    weekly: 'Weekly',
    runAt: 'Run at',
    weekdays: 'Weekdays',
    monday: 'Mon',
    tuesday: 'Tue',
    wednesday: 'Wed',
    thursday: 'Thu',
    friday: 'Fri',
    saturday: 'Sat',
    sunday: 'Sun',
    windowDays: 'Window days',
    maxJobs: 'Max jobs',
    autoEvaluateFit: 'Auto evaluate fit',
    autoGenerateCv: 'Auto generate CV',
    runNowOnCreate: 'Run crawl right after create',
    cronPreview: 'Cron preview',
    filteredJobs: 'Filtered Jobs',
    appliedJobsPipeline: 'Applied Jobs',
    details: 'Details',
    close: 'Close',
    linkedinLink: 'LinkedIn Link',
    actions: 'Actions',
    action: 'Action',
    generateCv: 'Generate CV',
    generateSelectedCv: 'Generate Selected CV',
    applySelected: 'Apply Selected',
    selectCvFiles: 'Select CV files',
    processingApply: 'Applying...',
    processingCv: 'Processing CV...',
    cvGenerated: 'CV generated',
    previewCv: 'Preview CV',
    selectAll: 'Select all',
    delete: 'Delete',
    confirmDeleteSchedule: 'Delete this schedule?',
    selected: 'selected',
    noSelection: 'No selection',
    search: 'Search',
    clear: 'Clear',
    apply: 'Apply',
    appliedByManual: 'Applied by manual',
    markAppliedManual: 'Mark Applied Manual',
    manualApplied: 'Manual applied',
    appliedManualNote: 'Manual apply note',
    manualReview: 'Manual Review',
    applyError: 'Apply Error',
    priorityFlag: 'Priority Flag',
    lowPriority: 'Low Priority',
    manualOnly: 'Manual Only',
    companyUnderReview: 'Already under review at company',
    noLongerAccepting: 'No longer accepting applications',
    onsiteOnly: 'Onsite only',
    fullTimeOnly: 'Full-time only',
    partTimeOnly: 'Part-time only',
    contractOnly: 'Contract only',
    internshipOnly: 'Internship only',
    jobRule: 'Job Rule',
    companyRule: 'Company Rule',
    effectiveRule: 'Effective Rule',
    standardFlow: 'Standard flow',
    reviewLater: 'Review later',
    companyDefault: 'No company default',
    jobOverride: 'No job override',
    closedStopApply: 'Closed / stop apply',
    jobRuleHint: 'Job rule overrides company rule when both are set.',
    jobRuleDesc: 'Use for one specific JD.',
    companyRuleDesc: 'Use as default for all jobs from this company.',
    priorityNote: 'Priority Note',
    clearAllFilters: 'Clear All Filters',
    showing: 'Showing',
    of: 'of',
    records: 'records',
    en: 'English',
    vi: 'Vietnamese',
    other: 'Other',
  },
  vi: {
    appTitle: 'Báº£ng Ä‘iá»u khiá»ƒn Job Ops',
    backendHealth: 'Tráº¡ng thÃ¡i Backend',
    dashboard: 'Tá»•ng quan',
    jobs: 'Viá»‡c lÃ m',
    appliedJobsPage: 'Viá»‡c Ä‘Ã£ á»©ng tuyá»ƒn',
    analytics: 'PhÃ¢n tÃ­ch Ä‘Äƒng láº¡i',
    automation: 'Váº­n hÃ nh',
    learningQuiz: 'Học & Quiz',
    knowledgeTab: 'Lý thuyết',
    interviewQaTab: 'Interview Q&A',
    knowledgeHint: 'Xem nhanh phần lý thuyết và giải thích trước khi làm quiz.',
    topic: 'Chá»§ Ä‘á»',
    startQuiz: 'Báº¯t Ä‘áº§u quiz',
    submitQuiz: 'Ná»™p bÃ i',
    quizHistory: 'Lá»‹ch sá»­ quiz',
    explanation: 'Giáº£i thÃ­ch',
    correctAnswer: 'ÄÃ¡p Ã¡n Ä‘Ãºng',
    yourAnswer: 'CÃ¢u tráº£ lá»i cá»§a báº¡n',
    score: 'Äiá»ƒm',
    scheduleLearningEtl: 'Láº­p lá»‹ch Learning ETL',
    queue: 'HÃ ng Ä‘á»£i',
    nextRun: 'Láº§n cháº¡y káº¿',
    noQuizQuestions: 'ChÆ°a cÃ³ cÃ¢u há»i quiz.',
    totalJobs: 'Tá»•ng sá»‘ viá»‡c lÃ m',
    appliedJobs: 'Viá»‡c Ä‘Ã£ á»©ng tuyá»ƒn',
    respondedJobs: 'Viá»‡c Ä‘Ã£ pháº£n há»“i',
    cvReadyJobs: 'Viá»‡c lÃ m sáºµn sÃ ng cho CV',
    crawlRuns: 'LÆ°á»£t crawl',
    recentRuns: 'Láº§n cháº¡y gáº§n Ä‘Ã¢y',
    loadingDashboard: 'Äang táº£i tá»•ng quan...',
    filter: 'Lá»c',
    all: 'Táº¥t cáº£',
    filtered: 'ÄÃ£ lá»c',
    applied: 'ÄÃ£ á»©ng tuyá»ƒn',
    company: 'CÃ´ng ty',
    searchPlaceholder: 'TÃ¬m kiáº¿m tiÃªu Ä‘á»/cÃ´ng ty',
    evaluateFit: 'ÄÃ¡nh giÃ¡ sá»± phÃ¹ há»£p',
    constraintMode: 'Má»©c rá»™ng buá»™c',
    hard: 'Cá»©ng',
    medium: 'Trung bÃ¬nh',
    soft: 'Má»m',
    evaluating: 'Äang Ä‘Ã¡nh giÃ¡...',
    loading: 'Äang táº£i...',
    country: 'Quá»‘c gia',
    workModel: 'HÃ¬nh thá»©c lÃ m viá»‡c',
    employmentType: 'Loáº¡i cÃ´ng viá»‡c',
    easyApply: 'Easy Apply',
    programLanguage: 'NgÃ´n ngá»¯ láº­p trÃ¬nh',
    languageFilter: 'NgÃ´n ngá»¯',
    response: 'Pháº£n há»“i',
    fit: 'PhÃ¹ há»£p',
    fitScore: 'Diem Fit',
    fitReason: 'LÃ½ do Ä‘Ã¡nh giÃ¡',
    yes: 'CÃ³',
    no: 'KhÃ´ng',
    notEvaluated: 'chÆ°a Ä‘Ã¡nh giÃ¡',
    firstSeen: 'Tháº¥y láº§n Ä‘áº§u',
    lastSeen: 'Tháº¥y láº§n cuá»‘i',
    noJdText: 'KhÃ´ng cÃ³ JD text',
    run: 'Cháº¡y',
    minReposts: 'Sá»‘ láº§n Ä‘Äƒng láº¡i tá»‘i thiá»ƒu',
    location: 'Äá»‹a Ä‘iá»ƒm',
    reposts: 'ÄÄƒng láº¡i',
    durationDays: 'Sá»‘ ngÃ y',
    first: 'Äáº§u',
    last: 'Cuá»‘i',
    distinctPosts: 'Sá»‘ bÃ i Ä‘Äƒng',
    manualActions: 'TÃ¡c vá»¥ thá»§ cÃ´ng',
    runCrawlFiltered: 'Run Crawl Filtered',
    runCrawlApplied: 'Run Crawl Applied',
    runGenerateCv: 'Run Generate CV',
    runGenerateInterviewQa: 'Generate Interview Q&A',
    pauseRun: 'Pause',
    predictJobIds: 'Job IDs',
    predictJobIdsPlaceholder: 'e.g. 4381111111,4382222222',
    predictCvPath: 'CV path',
    predictJdText: 'JD text',
    predictJdFile: 'JD file',
    predictJdHint: 'Paste JD text or upload a JD file for ad-hoc predictions.',
    predictRecentDays: 'Recent days',
    predictMaxJobs: 'Max jobs',
    predictStartAt: 'Start job time',
    predictForce: 'Force run even when feature flag is off',
    learningEtlPipeline: 'Learning ETL',
    shutdownWhenCompleted: 'Shut down when completed',
    createSchedule: 'Táº¡o lá»‹ch',
    create: 'Táº¡o',
    schedules: 'Schedules',
    editSchedule: 'Edit schedule',
    saveChanges: 'Save Changes',
    cancelEditSchedule: 'Cancel Edit',
    pauseSchedule: 'Pause schedule',
    resumeSchedule: 'Resume schedule',
    enabled: 'Báº­t',
    cron: 'Cron',
    pipeline: 'Pipeline',
    threshold: 'NgÆ°á»¡ng',
    status: 'Tráº¡ng thÃ¡i',
    startedGmt7: 'Báº¯t Ä‘áº§u (GMT+7)',
    language: 'NgÃ´n ngá»¯',
    automationSummary: 'Tá»•ng há»£p láº§n cháº¡y',
    successRuns: 'ThÃ nh cÃ´ng',
    failedRuns: 'Tháº¥t báº¡i',
    lastRunGmt7: 'Láº§n cháº¡y cuá»‘i (GMT+7)',
    postedDate: 'NgÃ y Ä‘Äƒng LinkedIn',
    applyDate: 'NgÃ y apply',
    postedTimeText: 'Chuá»—i thá»i gian Ä‘Äƒng',
    page: 'Trang',
    prev: 'TrÆ°á»›c',
    next: 'Sau',
    pageSize: 'KÃ­ch thÆ°á»›c trang',
    sortPostedDesc: 'NgÃ y Ä‘Äƒng má»›i nháº¥t',
    sortPostedAsc: 'NgÃ y Ä‘Äƒng cÅ© nháº¥t',
    sortDesc: 'Giam dan',
    sortAsc: 'Tang dan',
    fitSort: 'Sap xep fit',
    sortSeenDesc: 'NgÃ y tháº¥y má»›i nháº¥t',
    sortSeenAsc: 'NgÃ y tháº¥y cÅ© nháº¥t',
    postedWithinDays: 'ÄÄƒng trong vÃ²ng (ngÃ y)',
    postedWindow: 'Khoang ngay dang',
    last1Day: '1 ngay gan day',
    last1Week: '1 tuan gan day',
    last1Month: '1 thang gan day',
    customDays: 'So ngay tuy chon',
    estimatedFromText: 'Æ°á»›c tÃ­nh tá»« chuá»—i thá»i gian',
    scheduleName: 'TÃªn lá»‹ch',
    scheduleType: 'Loáº¡i pipeline',
    frequency: 'Táº§n suáº¥t',
    everyHours: 'Má»—i N giá»',
    daily: 'HÃ ng ngÃ y',
    weekly: 'HÃ ng tuáº§n',
    runAt: 'Cháº¡y lÃºc',
    weekdays: 'NgÃ y cháº¡y',
    monday: 'Thá»© 2',
    tuesday: 'Thá»© 3',
    wednesday: 'Thá»© 4',
    thursday: 'Thá»© 5',
    friday: 'Thá»© 6',
    saturday: 'Thá»© 7',
    sunday: 'CN',
    windowDays: 'Sá»‘ ngÃ y láº¥y dá»¯ liá»‡u',
    maxJobs: 'Sá»‘ job tá»‘i Ä‘a',
    autoEvaluateFit: 'Tá»± Ä‘á»™ng Ä‘Ã¡nh giÃ¡ fit',
    autoGenerateCv: 'Tá»± Ä‘á»™ng táº¡o CV',
    runNowOnCreate: 'Tao xong chay crawl ngay',
    cronPreview: 'Cron táº¡o ra',
    filteredJobs: 'Viá»‡c lÃ m theo bá»™ lá»c',
    appliedJobsPipeline: 'Viá»‡c Ä‘Ã£ á»©ng tuyá»ƒn',
    details: 'Chi tiáº¿t',
    close: 'ÄÃ³ng',
    linkedinLink: 'LiÃªn káº¿t LinkedIn',
    actions: 'Thao tÃ¡c',
    action: 'Hanh dong',
    generateCv: 'Tao CV',
    generateSelectedCv: 'Tao CV da chon',
    applySelected: 'Apply vao job da chon',
    selectCvFiles: 'Chon file CV',
    processingApply: 'Dang apply...',
    processingCv: 'Dang xu ly CV...',
    cvGenerated: 'Da tao CV',
    previewCv: 'Xem CV',
    selectAll: 'Chon tat ca',
    delete: 'XÃ³a',
    confirmDeleteSchedule: 'XÃ³a lá»‹ch nÃ y?',
    selected: 'Ä‘Ã£ chá»n',
    noSelection: 'ChÆ°a chá»n',
    search: 'TÃ¬m',
    clear: 'XÃ³a',
    apply: 'Ãp dá»¥ng',
    appliedByManual: 'ÄÃ£ apply thá»§ cÃ´ng',
    markAppliedManual: 'Mark Applied Manual',
    manualApplied: 'Manual applied',
    appliedManualNote: 'Ghi chÃº apply thá»§ cÃ´ng',
    manualReview: 'Can xu ly thu cong',
    applyError: 'Loi apply',
    priorityFlag: 'Co uu tien',
    lowPriority: 'Uu tien thap',
    manualOnly: 'Chi xu ly thu cong',
    companyUnderReview: 'Da ung tuyen cong ty va dang duoc review',
    noLongerAccepting: 'Khong con nhan ung tuyen',
    onsiteOnly: 'Chi onsite',
    fullTimeOnly: 'Chi full-time',
    partTimeOnly: 'Chi part-time',
    contractOnly: 'Chi contract',
    internshipOnly: 'Chi internship',
    jobRule: 'Rule cua job',
    companyRule: 'Rule cua cong ty',
    effectiveRule: 'Rule dang ap dung',
    standardFlow: 'Xu ly binh thuong',
    reviewLater: 'Xem lai sau',
    companyDefault: 'Khong co mac dinh cong ty',
    jobOverride: 'Khong co override cho job',
    closedStopApply: 'Dong / dung apply',
    jobRuleHint: 'Rule cua job se uu tien hon rule cua cong ty.',
    jobRuleDesc: 'Dung cho rieng job nay.',
    companyRuleDesc: 'Dung lam mac dinh cho moi job cua cong ty nay.',
    priorityNote: 'Ghi chu uu tien',
    clearAllFilters: 'XÃ³a toÃ n bá»™ bá»™ lá»c',
    showing: 'Hiá»ƒn thá»‹',
    of: 'trÃªn',
    records: 'báº£n ghi',
    en: 'Tiáº¿ng Anh',
    vi: 'Tiáº¿ng Viá»‡t',
    other: 'KhÃ¡c',
  },
}

const statusText = {
  en: { success: 'Success', failed: 'Failed', running: 'Running', pending: 'Pending', completed: 'Completed', unknown: 'Unknown' },
  vi: { success: 'ThÃ nh cÃ´ng', failed: 'Tháº¥t báº¡i', running: 'Äang cháº¡y', pending: 'Cho cháº¡y', completed: 'HoÃ n táº¥t', unknown: 'KhÃ´ng rÃµ' },
}

const weekdayOptions = [
  { key: 'monday', value: 1 },
  { key: 'tuesday', value: 2 },
  { key: 'wednesday', value: 3 },
  { key: 'thursday', value: 4 },
  { key: 'friday', value: 5 },
  { key: 'saturday', value: 6 },
  { key: 'sunday', value: 0 },
]

const PAGE_SIZE_OPTIONS = [10, 20, 30, 40, 50, 70, 90, 100]
const WORK_MODEL_OPTIONS = [
  { label: 'Remote', value: 'remote' },
  { label: 'Hybrid', value: 'hybrid' },
  { label: 'On-site', value: 'on_site' },
]
const EMPLOYMENT_TYPE_OPTIONS = [
  { label: 'Full-time', value: 'full_time' },
  { label: 'Part-time', value: 'part_time' },
  { label: 'Contract', value: 'contract' },
  { label: 'Internship', value: 'internship' },
  { label: 'Temporary', value: 'temporary' },
  { label: 'Volunteer', value: 'volunteer' },
]
const WORLD_COUNTRY_FEATURES = topojsonFeature(worldAtlas, worldAtlas.objects.countries).features
const COUNTRY_NAME_ALIASES = {
  usa: 'united states of america',
  'u s a': 'united states of america',
  'u s': 'united states of america',
  'united states': 'united states of america',
  'dominican republic': 'dominican rep',
  'bosnia and herzegovina': 'bosnia and herz',
  'czech republic': 'czechia',
  'russian federation': 'russia',
  'viet nam': 'vietnam',
  'korea republic of': 'south korea',
  'republic of korea': 'south korea',
  'korea democratic peoples republic of': 'north korea',
  'iran islamic republic of': 'iran',
  'moldova republic of': 'moldova',
  'venezuela bolivarian republic of': 'venezuela',
  'syrian arab republic': 'syria',
  'tanzania united republic of': 'tanzania',
  'brunei darussalam': 'brunei',
  'palestine state of': 'palestine',
  'cabo verde': 'cape verde',
  'ivory coast': "cote d'ivoire",
}

function formatGmt7(value, lang = 'en') {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const locale = lang === 'vi' ? 'vi-VN' : 'en-GB'
  const formatted = new Intl.DateTimeFormat(locale, {
    timeZone: TIMEZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
  return `${formatted} GMT+7`
}

function normalizeCountryKey(value) {
  const base = String(value || '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[.(),']/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return COUNTRY_NAME_ALIASES[base] || base
}

function heatColor(count, maxCount) {
  if (!count || count <= 0 || !maxCount) return '#d2d6dc'
  const ratio = Math.max(0, Math.min(1, Math.log1p(count) / Math.log1p(maxCount)))
  const hue = 120 - (ratio * 120)
  const lightness = 44 + ((1 - ratio) * 10)
  return `hsl(${hue}, 72%, ${lightness}%)`
}

function normalizeStatus(raw, lang) {
  const key = String(raw || '').trim().toLowerCase()
  if (['success', 'thanh cong', 'thÃ nh cÃ´ng'].includes(key)) return statusText[lang].success
  if (['failed', 'that bai', 'tháº¥t báº¡i'].includes(key)) return statusText[lang].failed
  if (['running', 'dang chay', 'Ä‘ang cháº¡y'].includes(key)) return statusText[lang].running
  if (['pending', 'cho chay', 'chá» cháº¡y'].includes(key)) return statusText[lang].pending
  if (['completed', 'hoan tat', 'hoÃ n táº¥t'].includes(key)) return statusText[lang].completed
  return statusText[lang].unknown
}

function parseTime(value) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(value || '').trim())
  if (!m) return { hour: 9, minute: 0 }
  const hour = Math.min(23, Math.max(0, Number(m[1])))
  const minute = Math.min(59, Math.max(0, Number(m[2])))
  return { hour, minute }
}

function buildCronExpr(ui) {
  if (ui.frequency === 'daily') {
    const { hour, minute } = parseTime(ui.run_time)
    return `${minute} ${hour} * * *`
  }
  if (ui.frequency === 'weekly') {
    const { hour, minute } = parseTime(ui.run_time)
    const days = (ui.weekdays || []).length ? ui.weekdays : [1]
    return `${minute} ${hour} * * ${days.join(',')}`
  }
  const every = Math.min(24, Math.max(1, Number(ui.every_hours || 6)))
  if (every === 24) return '0 0 * * *'
  return `0 */${every} * * *`
}

function parseScheduleFormFromCron(cronExpr, fallback = {}) {
  const cron = String(cronExpr || '').trim()
  const dailyMatch = /^(\d{1,2}) (\d{1,2}) \* \* \*$/.exec(cron)
  const everyHoursMatch = /^0 \*\/(\d{1,2}) \* \* \*$/.exec(cron)
  const weeklyMatch = /^(\d{1,2}) (\d{1,2}) \* \* ([\d,]+)$/.exec(cron)
  if (everyHoursMatch) {
    return {
      ...fallback,
      frequency: 'every_hours',
      every_hours: String(Math.min(24, Math.max(1, Number(everyHoursMatch[1]) || 6))),
    }
  }
  if (weeklyMatch) {
    return {
      ...fallback,
      frequency: 'weekly',
      run_time: `${String(weeklyMatch[2]).padStart(2, '0')}:${String(weeklyMatch[1]).padStart(2, '0')}`,
      weekdays: weeklyMatch[3].split(',').map((day) => Number(day)).filter((day) => Number.isFinite(day)).sort((a, b) => a - b),
    }
  }
  if (dailyMatch) {
    return {
      ...fallback,
      frequency: 'daily',
      run_time: `${String(dailyMatch[2]).padStart(2, '0')}:${String(dailyMatch[1]).padStart(2, '0')}`,
    }
  }
  return fallback
}

function normalizeSortValue(value) {
  if (value === null || value === undefined) return ''
  if (typeof value === 'number') return value
  const text = String(value).trim()
  const n = Number(text)
  if (!Number.isNaN(n) && text !== '') return n
  return text.toLowerCase()
}

function sortRows(rows, sort) {
  const { key, dir } = sort || {}
  if (!key || !dir) return rows
  const factor = dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const aFlag = String(a?.effective_priority_flag || '').trim().toLowerCase()
    const bFlag = String(b?.effective_priority_flag || '').trim().toLowerCase()
    const aLow = aFlag === 'low_priority' ? 1 : 0
    const bLow = bFlag === 'low_priority' ? 1 : 0
    if (aLow !== bLow) return aLow - bLow
    const aClosed = aFlag === 'closed_no_longer_accepting' ? 1 : 0
    const bClosed = bFlag === 'closed_no_longer_accepting' ? 1 : 0
    if (aClosed !== bClosed) return aClosed - bClosed
    const aRejected = ['manual_only', 'company_under_review', 'onsite_only', 'full_time_only', 'part_time_only', 'contract_only', 'internship_only'].includes(aFlag) ? 1 : 0
    const bRejected = ['manual_only', 'company_under_review', 'onsite_only', 'full_time_only', 'part_time_only', 'contract_only', 'internship_only'].includes(bFlag) ? 1 : 0
    if (aRejected !== bRejected) return aRejected - bRejected
    const av = normalizeSortValue(a?.[key])
    const bv = normalizeSortValue(b?.[key])
    if (av < bv) return -1 * factor
    if (av > bv) return 1 * factor
    return 0
  })
}

function hasShutdownFlag(item) {
  return Boolean(item?.shutdown_when_completed || item?.crawl_config_json?.shutdown_when_completed)
}

function shutdownBadgeText(item) {
  const source = String(item?.shutdown_source || '').trim().toLowerCase()
  if (source === 'schedule+cli') return 'Shutdown: Schedule + CLI'
  if (source === 'schedule') return 'Shutdown: Schedule'
  if (source === 'cli') return 'Shutdown: CLI'
  return 'Shutdown'
}

function cvTaggedTextToHtml(value) {
  const raw = String(value || '')
  const escaped = raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  const restoredTags = escaped.replace(
    /&lt;(\/?)(bold|italic|green|orange|center)&gt;/gi,
    (_m, slash, name) => `<${slash}${String(name).toLowerCase()}>`,
  )

  const mapped = restoredTags
    .replace(/<bold>/g, '<strong>')
    .replace(/<\/bold>/g, '</strong>')
    .replace(/<italic>/g, '<em>')
    .replace(/<\/italic>/g, '</em>')
    .replace(/<green>/g, '<span class="cv-green">')
    .replace(/<\/green>/g, '</span>')
    .replace(/<orange>/g, '<span class="cv-orange">')
    .replace(/<\/orange>/g, '</span>')
    .replace(/<center>/g, '<div class="cv-center">')
    .replace(/<\/center>/g, '</div>')

  return mapped.replace(/\r\n/g, '\n').replace(/\r/g, '\n').replace(/\n/g, '<br/>')
}

function paginateRows(rows, page, pageSize) {
  const total = rows.length
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const safePage = Math.max(1, Math.min(page, totalPages))
  const start = (safePage - 1) * pageSize
  const end = Math.min(start + pageSize, total)
  return {
    items: rows.slice(start, end),
    total,
    totalPages,
    page: safePage,
    start: total === 0 ? 0 : start + 1,
    end,
  }
}

function SortTh({ label, col, sort, onSort }) {
  const active = sort.key === col
  const mark = active ? (sort.dir === 'asc' ? '▲' : '▼') : ''
  return (
    <th>
      <button className="sort-btn" onClick={() => onSort(col)}>
        {label} {mark}
      </button>
    </th>
  )
}

function CheckboxMultiSelect({ options, groups, selected, onChange, t, label, applyMode = false, includeGroupValue = true }) {
  const [query, setQuery] = useState('')
  const [draftSelected, setDraftSelected] = useState(selected || [])
  const selectedSet = new Set(selected || [])
  const draftSet = new Set(draftSelected || [])
  const summarySet = applyMode ? draftSet : selectedSet
  const summary = summarySet.size ? `${summarySet.size} ${t.selected}` : t.noSelection

  useEffect(() => {
    setDraftSelected(selected || [])
  }, [selected])
  const ordered = useMemo(() => {
    const map = new Map()
    for (const opt of options || []) {
      const value = String(opt?.value ?? '').trim()
      const text = String(opt?.label ?? value).trim()
      if (!value || !text) continue
      if (!map.has(value)) map.set(value, { value, label: text })
    }
    const rank = (text) => {
      if (/^[A-Z]{2,3}$/.test(text)) return 2
      if (/(area|metropolitan|union|region|row)$/i.test(text)) return 1
      return 0
    }
    return Array.from(map.values()).sort((a, b) => {
      const aSel = selectedSet.has(a.value) ? 0 : 1
      const bSel = selectedSet.has(b.value) ? 0 : 1
      if (aSel !== bSel) return aSel - bSel
      const ra = rank(a.label)
      const rb = rank(b.label)
      if (ra !== rb) return ra - rb
      return a.label.localeCompare(b.label, 'en', { sensitivity: 'base' })
    })
  }, [options, selected])
  const q = query.trim().toLowerCase()
  const normalizedGroups = useMemo(() => {
    const groupList = Array.isArray(groups) ? groups : []
    const result = []
    for (const g of groupList) {
      const groupLabel = String(g?.region ?? g?.group ?? g?.label ?? '').trim()
      if (!groupLabel) continue
      const childMap = new Map()
      const rawItems = Array.isArray(g?.countries) ? g.countries : (Array.isArray(g?.languages) ? g.languages : (Array.isArray(g?.items) ? g.items : []))
      for (const c of rawItems) {
        const itemValue = String(c?.country ?? c?.language ?? c?.value ?? c?.label ?? c ?? '').trim()
        if (!itemValue) continue
        if (!childMap.has(itemValue)) childMap.set(itemValue, { value: itemValue, label: itemValue })
      }
      const children = Array.from(childMap.values())
      result.push({ value: groupLabel, label: groupLabel, children })
    }
    return result
  }, [groups])

  const filteredGroups = useMemo(() => {
    if (!normalizedGroups.length) return []
    const activeSet = applyMode ? draftSet : selectedSet
    const prioritized = normalizedGroups
      .map((group, idx) => {
        const children = group.children || []
        const selectedChildren = children.filter((c) => activeSet.has(c.value)).length
        const selectedGroup = activeSet.has(group.value)
        const priority = selectedGroup || selectedChildren > 0 ? 0 : 1
        return { group, idx, priority, selectedChildren }
      })
      .sort((a, b) => {
        if (a.priority !== b.priority) return a.priority - b.priority
        if (a.selectedChildren !== b.selectedChildren) return b.selectedChildren - a.selectedChildren
        return a.idx - b.idx
      })
      .map((x) => x.group)
    if (!q) return prioritized
    const out = []
    for (const group of prioritized) {
      const groupMatch = group.label.toLowerCase().includes(q)
      const matchedChildren = groupMatch
        ? group.children
        : group.children.filter((c) => c.label.toLowerCase().includes(q))
      if (groupMatch || matchedChildren.length > 0) {
        out.push({ ...group, children: matchedChildren })
      }
    }
    return out
  }, [normalizedGroups, q, applyMode, draftSelected, selected])

  const filtered = !q
    ? ordered
    : ordered.filter((opt) => String(opt.label || '').toLowerCase().includes(q))

  function applyGroupToggle(group, checked) {
    const baseSet = applyMode ? draftSet : selectedSet
    const next = new Set(baseSet)
    const children = group?.children || []
    if (checked) {
      if (includeGroupValue) next.add(group.value)
      for (const child of children) next.add(child.value)
    } else {
      next.delete(group.value)
      for (const child of children) next.delete(child.value)
    }
    if (applyMode) setDraftSelected(Array.from(next))
    else onChange(Array.from(next))
  }

  return (
    <details className="multi-box">
      <summary>{label}: {summary}</summary>
      <div className="multi-panel">
        <div className="multi-toolbar">
          <input
            className="multi-search"
            placeholder={t.search}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button
            className="mini-btn"
            onClick={(e) => {
              e.preventDefault()
              if (applyMode) setDraftSelected([])
              else onChange([])
            }}
          >
            {t.clear}
          </button>
          {applyMode && (
            <button
              className="mini-btn"
              onClick={(e) => {
                e.preventDefault()
                onChange(Array.from(draftSet))
              }}
            >
              {t.apply || 'Apply'}
            </button>
          )}
        </div>
        {filteredGroups.length > 0 ? filteredGroups.map((group) => {
          const allChildrenSelected = (group.children || []).length > 0
            && group.children.every((child) => (applyMode ? draftSet.has(child.value) : selectedSet.has(child.value)))
          const groupChecked = includeGroupValue
            ? ((applyMode ? draftSet.has(group.value) : selectedSet.has(group.value)) || allChildrenSelected)
            : allChildrenSelected
          return (
            <div key={group.value} className="multi-group">
              <label className="multi-item multi-item-region">
                <input
                  type="checkbox"
                  checked={groupChecked}
                  onChange={(e) => applyGroupToggle(group, e.target.checked)}
                />
                <span>{group.label}</span>
              </label>
              {(group.children || []).map((opt) => (
                <label key={`${group.value}__${opt.value}`} className="multi-item multi-item-child">
                  <input
                    type="checkbox"
                    checked={applyMode ? draftSet.has(opt.value) : selectedSet.has(opt.value)}
                    onChange={(e) => {
                      const baseSet = applyMode ? draftSet : selectedSet
                      const next = new Set(baseSet)
                      if (e.target.checked) next.add(opt.value)
                      else next.delete(opt.value)
                      if (applyMode) setDraftSelected(Array.from(next))
                      else onChange(Array.from(next))
                    }}
                  />
                  <span>{opt.label}</span>
                </label>
              ))}
            </div>
          )
        }) : filtered.map((opt) => (
          <label key={String(opt.value)} className="multi-item">
            <input
              type="checkbox"
              checked={applyMode ? draftSet.has(opt.value) : selectedSet.has(opt.value)}
              onChange={(e) => {
                const baseSet = applyMode ? draftSet : selectedSet
                const next = new Set(baseSet)
                if (e.target.checked) next.add(opt.value)
                else next.delete(opt.value)
                if (applyMode) setDraftSelected(Array.from(next))
                else onChange(Array.from(next))
              }}
            />
            <span>{opt.label}</span>
          </label>
        ))}
      </div>
    </details>
  )
}

function Modal({ open, onClose, title, children, t }) {
  if (!open) return null
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button onClick={onClose}>{t.close}</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}

function Card({ title, value, onClick }) {
  return (
    <div className={`card metric ${onClick ? 'card-clickable' : ''}`} onClick={onClick}>
      <div className="muted">{title}</div>
      <div className="value">{value}</div>
    </div>
  )
}

function formatCompanyWithCountry(job) {
  const company = String(job?.company || '').trim()
  const country = String(job?.country || job?.normalized_country || '').trim()
  if (!company) return '-'
  if (!country) return company
  const companyLower = company.toLowerCase()
  const countryLower = country.toLowerCase()
  if (companyLower.endsWith(`(${countryLower})`) || companyLower.endsWith(`- ${countryLower}`)) {
    return company
  }
  return `${company} (${country})`
}

function fitIssueMetricLabel(metric) {
  const key = String(metric || '').trim().toLowerCase()
  if (key === 'constraint') return 'Constraint'
  if (key === 'domain') return 'Domain'
  if (key === 'tech') return 'Technical'
  if (key === 'evidence') return 'Evidence'
  if (key === 'compliance') return 'Compliance'
  return 'Issue'
}

function renderFitPrimaryIssue(detail) {
  const text = String(detail?.primary_issue_text || '').trim()
  const metric = String(detail?.primary_issue_metric || '').trim()
  if (!text && !metric) return null
  const scoreValue = Number(detail?.primary_issue_score)
  const hasScore = Number.isFinite(scoreValue)
  const label = fitIssueMetricLabel(metric)
  return `Main issue: ${label}${hasScore ? ` (${scoreValue.toFixed(2)})` : ''} — ${text || '-'}`
}

function AppliedJobsChart({ points, t }) {
  const initialTrendView = useMemo(() => readSessionJson(APPLIED_TREND_VIEW_KEY, {}), [])
  const [zoomX, setZoomX] = useState(() => {
    const nextZoom = Number(initialTrendView?.zoomX)
    if (!Number.isFinite(nextZoom)) return 1
    return Math.max(0.25, Math.min(3, nextZoom))
  })
  const [hoveredPoint, setHoveredPoint] = useState(null)
  const scrollRef = useRef(null)
  const dragRef = useRef({ active: false, startX: 0, scrollLeft: 0, moved: false })
  const savedScrollLeftRef = useRef(Number(initialTrendView?.scrollLeft) || 0)
  const chartPoints = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10)
    const sourcePoints = Array.isArray(points) ? points : []
    if (!sourcePoints.length) {
      return [{
        apply_date: today,
        applied_count: 0,
        cumulative_count: 0,
      }]
    }

    const normalized = sourcePoints
      .map((point) => ({
        apply_date: String(point?.apply_date || '').slice(0, 10),
        applied_count: Number(point?.applied_count || 0),
        cumulative_count: Number(point?.cumulative_count || 0),
      }))
      .filter((point) => point.apply_date)
      .sort((a, b) => a.apply_date.localeCompare(b.apply_date))

    if (!normalized.length) {
      return [{
        apply_date: today,
        applied_count: 0,
        cumulative_count: 0,
      }]
    }

    const filled = [...normalized]
    let cursor = new Date(`${filled[filled.length - 1].apply_date}T00:00:00`)
    const end = new Date(`${today}T00:00:00`)
    let lastCumulative = Number(filled[filled.length - 1].cumulative_count || 0)
    while (cursor < end) {
      cursor.setDate(cursor.getDate() + 1)
      const dateKey = cursor.toISOString().slice(0, 10)
      filled.push({
        apply_date: dateKey,
        applied_count: 0,
        cumulative_count: lastCumulative,
      })
    }
    return filled
  }, [points])

  const rotationDeg = 28
  const rotationRad = (rotationDeg * Math.PI) / 180
  const yAxisFontSize = Math.max(8.5, Math.min(11, 7.5 + (zoomX * 3.5)))
  const xAxisFontSize = Math.max(8, Math.min(13, 6 + (zoomX * 7)))
  const maxDateChars = Math.max(...chartPoints.map((point) => String(point.apply_date || '').length), 10)
  const maxValue = Math.max(
    1,
    ...chartPoints.map((p) => Number(p.applied_count || 0)),
    ...chartPoints.map((p) => Number(p.cumulative_count || 0)),
  )
  const yTicks = Array.from({ length: 5 }, (_, i) => Math.round((maxValue * i) / 4))
  const maxYAxisChars = Math.max(...yTicks.map((tick) => String(tick).length), String(maxValue).length)
  const estimatedDateLabelWidth = maxDateChars * (xAxisFontSize * 0.62)
  const rotatedDateLabelHeight = Math.ceil(
    estimatedDateLabelWidth * Math.sin(rotationRad) + xAxisFontSize * Math.cos(rotationRad),
  )
  const rotatedDateLabelWidth = Math.ceil(
    estimatedDateLabelWidth * Math.cos(rotationRad) + xAxisFontSize * Math.sin(rotationRad),
  )
  const padLeft = Math.max(48, 18 + maxYAxisChars * (yAxisFontSize * 0.72))
  const padRight = Math.max(72, Math.ceil(rotatedDateLabelWidth * 0.28) + 16)
  const padTop = 18
  const padBottom = Math.max(104, rotatedDateLabelHeight + 42)
  const plotHeight = 198
  const minSpacingPerPoint = Math.max(72, rotatedDateLabelWidth + 10)
  const minViewportWidth = 420
  const minPlotWidth = Math.max(160, minViewportWidth - padLeft - padRight)
  const plotWidth = Math.max(minPlotWidth, (chartPoints.length - 1) * minSpacingPerPoint * zoomX)
  const width = Math.ceil(padLeft + plotWidth + padRight)
  const height = Math.ceil(padTop + plotHeight + padBottom)

  const innerWidth = width - padLeft - padRight
  const innerHeight = height - padTop - padBottom

  const xFor = (index) => {
    if (chartPoints.length === 1) return padLeft + innerWidth / 2
    return padLeft + (index / (chartPoints.length - 1)) * innerWidth
  }
  const yFor = (value) => padTop + innerHeight - (Number(value || 0) / maxValue) * innerHeight
  const isSinglePoint = chartPoints.length === 1
  const pointCx = (index, series = 'daily') => {
    const base = xFor(index)
    if (!isSinglePoint) return base
    return base + (series === 'daily' ? -10 : 10)
  }

  const dailyPath = chartPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xFor(i)} ${yFor(p.applied_count)}`).join(' ')
  const cumulativePath = chartPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xFor(i)} ${yFor(p.cumulative_count)}`).join(' ')
  const xLabels = chartPoints
  const latestPoint = chartPoints[chartPoints.length - 1] || null
  const canZoomOut = zoomX > 0.25
  const canZoomIn = zoomX < 3
  const lineStrokeWidth = Math.max(0.9, Math.min(3, 0.6 + (zoomX * 1.35)))
  const stemStrokeWidth = Math.max(0.8, Math.min(2, 0.7 + (zoomX * 0.8)))
  const pointRadius = Math.max(2.4, Math.min(5, 1.8 + (zoomX * 2.2)))

  useEffect(() => {
    writeSessionJson(APPLIED_TREND_VIEW_KEY, {
      zoomX,
      scrollLeft: savedScrollLeftRef.current,
    })
  }, [zoomX])

  useEffect(() => {
    const node = scrollRef.current
    if (!node) return
    const nextScrollLeft = Math.max(0, Math.min(savedScrollLeftRef.current, node.scrollWidth - node.clientWidth))
    node.scrollLeft = nextScrollLeft
  }, [width])

  function handleChartWheel(event) {
    const node = scrollRef.current
    if (!node) return
    const rect = node.getBoundingClientRect()
    const pointerRatio = rect.width > 0 ? (event.clientX - rect.left + node.scrollLeft) / Math.max(node.scrollWidth, 1) : 0.5
    const delta = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX
    if (!delta) return
    const nextZoom = Math.max(0.25, Math.min(3, Math.round((zoomX + (delta < 0 ? 0.15 : -0.15)) * 100) / 100))
    if (nextZoom !== zoomX) {
      const currentAbsoluteX = pointerRatio * node.scrollWidth
      savedScrollLeftRef.current = Math.max(0, currentAbsoluteX - ((event.clientX - rect.left) || 0))
      setZoomX(nextZoom)
    }
    event.preventDefault()
  }

  function handleDragStart(event) {
    const node = scrollRef.current
    if (!node) return
    dragRef.current = {
      active: true,
      startX: event.clientX,
      scrollLeft: node.scrollLeft,
      moved: false,
    }
  }

  function handleDragMove(event) {
    const node = scrollRef.current
    if (!node || !dragRef.current.active) return
    const deltaX = event.clientX - dragRef.current.startX
    if (Math.abs(deltaX) > 3) dragRef.current.moved = true
    node.scrollLeft = dragRef.current.scrollLeft - deltaX
  }

  function handleDragEnd() {
    dragRef.current.active = false
  }

  function handleChartScroll(event) {
    const nextScrollLeft = Number(event.currentTarget.scrollLeft || 0)
    savedScrollLeftRef.current = nextScrollLeft
    writeSessionJson(APPLIED_TREND_VIEW_KEY, {
      zoomX,
      scrollLeft: nextScrollLeft,
    })
  }

  function handlePointHover(event, text) {
    const node = scrollRef.current
    if (!node) return
    const rect = node.getBoundingClientRect()
    setHoveredPoint({
      text,
      x: event.clientX - rect.left + node.scrollLeft,
      y: event.clientY - rect.top,
    })
  }

  function handlePointLeave() {
    setHoveredPoint(null)
  }

  return (
    <div className="applied-chart-wrap">
      <div className="applied-chart-toolbar">
        <div className="applied-chart-legend">
          <span><i className="legend-dot legend-daily" />Daily applied</span>
          <span><i className="legend-dot legend-cumulative" />Cumulative</span>
        </div>
        <div className="applied-chart-zoom">
          <button type="button" onClick={() => setZoomX((prev) => Math.max(0.25, Math.round((prev - 0.25) * 100) / 100))} disabled={!canZoomOut}>−</button>
          <span>{Math.round(zoomX * 100)}%</span>
          <button type="button" onClick={() => setZoomX((prev) => Math.min(3, Math.round((prev + 0.25) * 100) / 100))} disabled={!canZoomIn}>+</button>
        </div>
      </div>
      {latestPoint ? (
        <div className="applied-chart-summary">
          <span>Latest: {latestPoint.apply_date}</span>
          <span>Daily: {latestPoint.applied_count}</span>
          <span>Total: {latestPoint.cumulative_count}</span>
        </div>
      ) : null}
      {!points?.length ? (
        <div className="muted">No confirmed applied jobs in DB yet. Use `Applied by manual` or a successful apply flow to populate this trend.</div>
      ) : null}
      <div className="applied-chart-hint muted">Use mouse wheel or +/- to zoom the timeline. Drag to pan horizontally.</div>
      <div
        className="applied-chart-scroll"
        ref={scrollRef}
        onWheel={handleChartWheel}
        onWheelCapture={handleChartWheel}
        onScroll={handleChartScroll}
        onMouseDown={handleDragStart}
        onMouseMove={handleDragMove}
        onMouseUp={handleDragEnd}
        onMouseLeave={() => {
          handleDragEnd()
          handlePointLeave()
        }}
      >
        {hoveredPoint ? (
          <div
            className="applied-chart-tooltip"
            style={{
              left: `${hoveredPoint.x + 12}px`,
              top: `${hoveredPoint.y - 12}px`,
            }}
          >
            {hoveredPoint.text}
          </div>
        ) : null}
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="applied-chart"
          style={{ minWidth: `${width}px` }}
          role="img"
          aria-label={t.appliedJobs}
        >
          {yTicks.map((tick, tickIndex) => {
            const y = yFor(tick)
            return (
              <g key={`y-${tickIndex}-${tick}`}>
                <line x1={padLeft} y1={y} x2={width - padRight} y2={y} className="chart-grid-line" />
                <text x={padLeft - 8} y={y + 4} textAnchor="end" className="chart-axis-text" style={{ fontSize: `${yAxisFontSize}px` }}>{tick}</text>
              </g>
            )
          })}
          {!isSinglePoint ? <path d={dailyPath} className="chart-line chart-line-daily" style={{ strokeWidth: lineStrokeWidth }} /> : null}
          {!isSinglePoint ? <path d={cumulativePath} className="chart-line chart-line-cumulative" style={{ strokeWidth: lineStrokeWidth }} /> : null}
          {chartPoints.map((point, index) => (
            <g key={`${point.apply_date}-${index}`}>
              {isSinglePoint ? (
                <line
                  x1={pointCx(index, 'daily')}
                  y1={padTop + innerHeight}
                  x2={pointCx(index, 'daily')}
                  y2={yFor(point.applied_count)}
                  className="chart-line chart-line-daily chart-single-stem"
                  style={{ strokeWidth: stemStrokeWidth }}
                />
              ) : null}
              <circle
                cx={pointCx(index, 'daily')}
                cy={yFor(point.applied_count)}
                r={pointRadius}
                className="chart-point chart-point-daily"
                onMouseEnter={(event) => handlePointHover(event, `${point.apply_date} | Daily applied: ${point.applied_count}`)}
                onMouseMove={(event) => handlePointHover(event, `${point.apply_date} | Daily applied: ${point.applied_count}`)}
                onMouseLeave={handlePointLeave}
              >
                <title>{`${point.apply_date} | Daily applied: ${point.applied_count}`}</title>
              </circle>
              {isSinglePoint ? (
                <line
                  x1={pointCx(index, 'cumulative')}
                  y1={padTop + innerHeight}
                  x2={pointCx(index, 'cumulative')}
                  y2={yFor(point.cumulative_count)}
                  className="chart-line chart-line-cumulative chart-single-stem"
                  style={{ strokeWidth: stemStrokeWidth }}
                />
              ) : null}
              <circle
                cx={pointCx(index, 'cumulative')}
                cy={yFor(point.cumulative_count)}
                r={pointRadius}
                className="chart-point chart-point-cumulative"
                onMouseEnter={(event) => handlePointHover(event, `${point.apply_date} | Cumulative: ${point.cumulative_count}`)}
                onMouseMove={(event) => handlePointHover(event, `${point.apply_date} | Cumulative: ${point.cumulative_count}`)}
                onMouseLeave={handlePointLeave}
              >
                <title>{`${point.apply_date} | Cumulative: ${point.cumulative_count}`}</title>
              </circle>
            </g>
          ))}
          {xLabels.map((point, labelIndex) => {
            const index = chartPoints.indexOf(point)
            const isFirst = index === 0
            const isLast = index === chartPoints.length - 1
            const anchor = isFirst ? 'start' : isLast ? 'end' : 'middle'
            return (
              <g key={`x-${point.apply_date}-${labelIndex}`} transform={`translate(${xFor(index)} ${height - 34})`}>
                <text
                  textAnchor={anchor}
                  transform={`rotate(-${rotationDeg})`}
                  className="chart-axis-text chart-axis-date"
                  style={{ fontSize: `${xAxisFontSize}px` }}
                >
                  {point.apply_date}
                </text>
              </g>
            )
          })}
        </svg>
      </div>
    </div>
  )
}

function JobsWorldMap({ items, onSelectCountry }) {
  const shellRef = useRef(null)
  const svgRef = useRef(null)
  const viewportRef = useRef(null)
  const initialMapView = useMemo(() => readStoredState(JOBS_DENSITY_MAP_VIEW_KEY, {}), [])
  const [viewportWidth, setViewportWidth] = useState(920)
  const [zoom, setZoom] = useState(() => {
    const nextZoom = Number(initialMapView?.zoom)
    if (!Number.isFinite(nextZoom)) return 1
    return Math.max(0.8, Math.min(6, nextZoom))
  })
  const [pan, setPan] = useState(() => ({
    x: Number(initialMapView?.pan?.x) || 0,
    y: Number(initialMapView?.pan?.y) || 0,
  }))
  const [tooltip, setTooltip] = useState(null)
  const dragRef = useRef({ active: false, startX: 0, startY: 0, panX: 0, panY: 0, moved: false })
  const width = Math.max(940, Math.min(1800, Math.round(viewportWidth || 920)))
  const height = Math.max(340, Math.min(520, Math.round(width * 0.34)))

  useEffect(() => {
    const node = shellRef.current
    if (!node || typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver((entries) => {
      const nextWidth = entries?.[0]?.contentRect?.width
      if (!nextWidth) return
      setViewportWidth(nextWidth)
    })
    observer.observe(node)
    setViewportWidth(node.getBoundingClientRect().width || 920)
    return () => observer.disconnect()
  }, [])

  const projection = useMemo(
    () => geoMercator().fitExtent([[18, 18], [width - 18, height - 18]], { type: 'FeatureCollection', features: WORLD_COUNTRY_FEATURES }),
    [width, height],
  )
  const pathGenerator = useMemo(() => geoPath(projection), [projection])
  const densityMap = useMemo(() => {
    const map = new Map()
    for (const item of items || []) {
      const country = String(item?.country || '').trim()
      const key = normalizeCountryKey(country)
      if (!key) continue
      const current = map.get(key) || { country, jobs: 0, applied_jobs: 0 }
      current.jobs += Number(item?.jobs || 0)
      current.applied_jobs += Number(item?.applied_jobs || 0)
      if (!current.country && country) current.country = country
      map.set(key, current)
    }
    return map
  }, [items])
  const maxJobs = useMemo(
    () => Math.max(0, ...Array.from(densityMap.values()).map((item) => Number(item.jobs || 0))),
    [densityMap],
  )

  useEffect(() => {
    writeStoredState(JOBS_DENSITY_MAP_VIEW_KEY, { zoom, pan })
  }, [zoom, pan])

  function clampZoom(next) {
    return Math.max(0.8, Math.min(6, Math.round(next * 100) / 100))
  }

  function updateTooltip(event, item, featureName) {
    const rect = event.currentTarget.ownerSVGElement?.getBoundingClientRect()
    if (!rect) return
    setTooltip({
      x: event.clientX - rect.left + 12,
      y: event.clientY - rect.top + 12,
      country: item?.country || featureName,
      jobs: Number(item?.jobs || 0),
      appliedJobs: Number(item?.applied_jobs || 0),
    })
  }

  function getSvgPoint(clientX, clientY, target) {
    const svg = svgRef.current
    if (!svg) return null
    const point = svg.createSVGPoint()
    point.x = clientX
    point.y = clientY
    const matrix = target?.getScreenCTM?.()
    if (!matrix) return null
    return point.matrixTransform(matrix.inverse())
  }

  function handleWheel(event) {
    event.preventDefault()
    event.stopPropagation()
    const pointerSvg = getSvgPoint(event.clientX, event.clientY, svgRef.current)
    const pointerWorld = getSvgPoint(event.clientX, event.clientY, viewportRef.current)
    if (!pointerSvg || !pointerWorld) return
    const wheelStep = Math.max(0.3, Math.min(0.8, Math.abs(event.deltaY) / 240))
    const delta = event.deltaY < 0 ? wheelStep : -wheelStep
    setZoom((prevZoom) => {
      const nextZoom = clampZoom(prevZoom + delta)
      if (nextZoom === prevZoom) return prevZoom
      setPan({
        x: pointerSvg.x - (pointerWorld.x * nextZoom),
        y: pointerSvg.y - (pointerWorld.y * nextZoom),
      })
      return nextZoom
    })
  }

  function startDrag(event) {
    const pointerSvg = getSvgPoint(event.clientX, event.clientY, svgRef.current)
    if (!pointerSvg) return
    dragRef.current = {
      active: true,
      startX: pointerSvg.x,
      startY: pointerSvg.y,
      panX: pan.x,
      panY: pan.y,
      moved: false,
    }
  }

  function moveDrag(event) {
    if (!dragRef.current.active) return
    const pointerSvg = getSvgPoint(event.clientX, event.clientY, svgRef.current)
    if (!pointerSvg) return
    const dx = pointerSvg.x - dragRef.current.startX
    const dy = pointerSvg.y - dragRef.current.startY
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) dragRef.current.moved = true
    setPan({ x: dragRef.current.panX + dx, y: dragRef.current.panY + dy })
  }

  function endDrag() {
    dragRef.current.active = false
  }

  return (
    <div className="world-map-wrap">
      <div className="applied-chart-toolbar">
        <div className="applied-chart-legend">
          <span><i className="legend-dot world-map-low" />Low density</span>
          <span><i className="legend-dot world-map-high" />High density</span>
        </div>
        <div className="applied-chart-zoom">
          <button type="button" onClick={() => setZoom((prev) => clampZoom(prev - 0.25))} disabled={zoom <= 0.8}>−</button>
          <span>{Math.round(zoom * 100)}%</span>
          <button type="button" onClick={() => setZoom((prev) => clampZoom(prev + 0.25))} disabled={zoom >= 6}>+</button>
        </div>
      </div>
      <div className="applied-chart-hint muted">Drag to pan. Wheel or +/- to zoom. Click a country to open Jobs filtered by country.</div>
      <div className="world-map-shell" ref={shellRef} onWheel={handleWheel}>
        <svg
          ref={svgRef}
          viewBox={`0 0 ${width} ${height}`}
          className="world-map-chart"
          role="img"
          aria-label="Jobs density by country"
          onMouseDown={startDrag}
          onMouseMove={moveDrag}
          onMouseUp={endDrag}
          onMouseLeave={() => { endDrag(); setTooltip(null) }}
        >
          <rect x="0" y="0" width={width} height={height} className="world-map-ocean" />
          <g ref={viewportRef} transform={`matrix(${zoom} 0 0 ${zoom} ${pan.x} ${pan.y})`}>
              {WORLD_COUNTRY_FEATURES.map((countryFeature) => {
                const featureName = String(countryFeature?.properties?.name || '')
                const item = densityMap.get(normalizeCountryKey(featureName))
                const jobs = Number(item?.jobs || 0)
                const d = pathGenerator(countryFeature)
                if (!d) return null
                return (
                  <path
                    key={countryFeature.id || featureName}
                    d={d}
                    className={`world-map-country ${jobs > 0 ? 'world-map-country-active' : ''}`}
                    style={{ fill: heatColor(jobs, maxJobs), strokeWidth: 0.7 / zoom }}
                    onMouseMove={(event) => updateTooltip(event, item, featureName)}
                    onClick={() => {
                      if (dragRef.current.moved || !item?.country) return
                      onSelectCountry(item.country)
                    }}
                  >
                    <title>{`${item?.country || featureName}: ${jobs} jobs`}</title>
                  </path>
                )
              })}
          </g>
        </svg>
        {tooltip ? (
          <div className="world-map-tooltip" style={{ left: tooltip.x, top: tooltip.y }}>
            <div>{tooltip.country}</div>
            <div>Jobs: {tooltip.jobs}</div>
            <div>Applied: {tooltip.appliedJobs}</div>
          </div>
        ) : null}
      </div>
    </div>
  )
}

function ScrollTopButton({ onClick }) {
  return (
    <button type="button" className="scroll-top-btn" onClick={onClick} aria-label="Scroll to top" title="Scroll to top">
      ↑ Top
    </button>
  )
}

function DashboardTab({ data, trend, countryOverview, t, lang, onOpenJobs }) {
  const [sort, setSort] = useState({ key: 'id', dir: 'desc' })
  const dashboardView = useMemo(() => readStoredState(DASHBOARD_PAGINATION_KEY, {}), [])
  const [page, setPage] = useState(() => Number(dashboardView?.page) || 1)
  const [pageSize, setPageSize] = useState(() => Number(dashboardView?.pageSize) || 50)
  const sourceRows = data?.recent_runs || []
  const appliedSeries = trend?.series || data?.applied_jobs_daily || []
  const recentRows = useMemo(() => sortRows(sourceRows, sort), [sourceRows, sort])
  const pg = useMemo(() => paginateRows(recentRows, page, pageSize), [recentRows, page, pageSize])
  const onSort = (key) => setSort((prev) => ({ key, dir: prev.key === key && prev.dir === 'asc' ? 'desc' : 'asc' }))
  useEffect(() => {
    writeStoredState(DASHBOARD_PAGINATION_KEY, { page, pageSize })
  }, [page, pageSize])
  if (!data) return <div className="card">{t.loadingDashboard}</div>
  return (
    <div className="grid">
      <Card title={t.totalJobs} value={data.total_jobs} onClick={() => onOpenJobs({ stage: 'all', has_cv: -1 })} />
      <Card title={t.appliedJobs} value={data.applied_jobs} onClick={() => onOpenJobs({ stage: 'applied', has_cv: -1 })} />
      <Card title={t.respondedJobs} value={data.responded_jobs} />
      <Card title={t.cvReadyJobs} value={data.cv_ready_jobs} onClick={() => onOpenJobs({ stage: 'all', has_cv: 1 })} />
      <Card title={t.crawlRuns} value={data.crawl_runs} />
      <div className="card dashboard-map-card">
        <h3>Jobs Density Map</h3>
        <JobsWorldMap items={countryOverview} onSelectCountry={(country) => onOpenJobs({ countries: [country], offset: '0' })} />
      </div>
      <div className="card dashboard-trend-card">
        <h3>Applied Jobs Trend</h3>
        {trend?.source_used ? <div className="muted">source={trend.source_used}</div> : null}
        <AppliedJobsChart points={appliedSeries} t={t} />
      </div>
      <div className="card wide">
        <h3>{t.recentRuns}</h3>
        <div className="pager">
          <span>{t.showing} {pg.start}-{pg.end} {t.of} {pg.total} {t.records}</span>
          <span>{t.pageSize}</span>
          <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value) || 50); setPage(1) }}>
            {PAGE_SIZE_OPTIONS.map((size) => (
              <option key={size} value={size}>{size}</option>
            ))}
          </select>
          <button disabled={pg.page <= 1} onClick={() => setPage(pg.page - 1)}>{t.prev}</button>
          <span>{t.page} {pg.page}/{pg.totalPages}</span>
          <button disabled={pg.page >= pg.totalPages} onClick={() => setPage(pg.page + 1)}>{t.next}</button>
        </div>
        <table>
          <thead><tr><SortTh label="ID" col="id" sort={sort} onSort={onSort} /><SortTh label="Date" col="crawl_date" sort={sort} onSort={onSort} /><SortTh label="Mode" col="mode" sort={sort} onSort={onSort} /><SortTh label="Total" col="total_jobs" sort={sort} onSort={onSort} /><SortTh label={t.startedGmt7} col="started_at" sort={sort} onSort={onSort} /></tr></thead>
          <tbody>
            {pg.items.map((r) => (
              <tr key={r.id}><td>{r.id}</td><td>{r.crawl_date}</td><td>{r.mode}</td><td>{r.total_jobs}</td><td>{formatGmt7(r.started_at, lang)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function JobsTab({ countries, countryGroups, programmingLanguages, programmingLanguageGroups, t, preset, tabTitle = null, forceAppliedView = false }) {
  const jobsStateKey = forceAppliedView ? APPLIED_JOBS_STATE_KEY : JOBS_STATE_KEY
  const [items, setItems] = useState([])
  const [selectedJobIds, setSelectedJobIds] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState(null)
  const [cvPreview, setCvPreview] = useState(null)
  const [applyModalOpen, setApplyModalOpen] = useState(false)
  const [applyBusy, setApplyBusy] = useState(false)
  const [applyBusyJobId, setApplyBusyJobId] = useState(null)
  const [cvFileOptions, setCvFileOptions] = useState([])
  const [selectedApplyCvPaths, setSelectedApplyCvPaths] = useState([])
  const [cvPreviewText, setCvPreviewText] = useState('')
  const [cvPreviewTextLoading, setCvPreviewTextLoading] = useState(false)
  const [coverLetterText, setCoverLetterText] = useState('')
  const [coverLetterTextLoading, setCoverLetterTextLoading] = useState(false)
  const [reloadToken, setReloadToken] = useState(0)
  const [fitBusy, setFitBusy] = useState(false)
  const [fitInfo, setFitInfo] = useState('')
  const [cvBusy, setCvBusy] = useState(false)
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [cvBusyJobId, setCvBusyJobId] = useState(null)
  const [cvBusyBatch, setCvBusyBatch] = useState(false)
  const [generatedCvItems, setGeneratedCvItems] = useState([])
  const [jobsError, setJobsError] = useState('')
  const [sort, setSort] = useState({ key: 'linkedin_posted_date', dir: 'desc' })
  const defaultFilters = {
    stage: 'filtered',
    countries: [],
    work_models: [],
    employment_types: [],
    easy_apply: -1,
    programming_languages: [],
    constraint_mode: 'medium',
    has_cv: -1,
    search: '',
    sort_by: 'posted_date_desc',
    posted_within_days: '',
    limit: '50',
    offset: '0',
  }
  const persistedJobsState = useMemo(() => readStoredState(jobsStateKey, {}), [jobsStateKey])
  const [filters, setFilters] = useState(() => ({ ...defaultFilters, ...(persistedJobsState?.filters || {}) }))

  useEffect(() => {
    writeStoredState(jobsStateKey, { filters })
  }, [jobsStateKey, filters])

  useEffect(() => {
    if (preset) setFilters((prev) => ({ ...prev, ...preset, offset: '0' }))
  }, [preset])

  useEffect(() => {
    if (forceAppliedView) {
      setFilters((prev) => ({ ...prev, stage: 'applied', offset: '0' }))
    }
  }, [forceAppliedView])

  useEffect(() => {
    let cancelled = false
    const timer = setTimeout(async () => {
      setLoading(true)
      setJobsError('')
      try {
        const req = {
          ...filters,
          summary_only: 1,
          posted_within_days: String(filters.posted_within_days || '').trim(),
        }
        if (!req.posted_within_days) delete req.posted_within_days
        const res = await api.jobs(req)
        if (!cancelled) {
          setItems(res.items || [])
          setTotal(res.total || 0)
        }
      } catch (e) {
        if (!cancelled) {
          setItems([])
          setTotal(0)
          setJobsError(String(e?.message || e))
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [filters, reloadToken])

  function patchFilters(next) {
    setFilters((prev) => ({ ...prev, ...next }))
  }

  function clearAllFilters() {
    setFilters({ ...defaultFilters, limit: filters.limit || '50', offset: '0' })
    setReloadToken((n) => n + 1)
  }

  async function openDetail(id) {
    try {
      const res = await api.jobDetail(id, filters.constraint_mode || 'medium')
      setDetail(res)
      setItems((prev) => prev.map((row) => (Number(row.id) === Number(id) ? { ...row, ...res } : row)))
    } catch (e) {
      setJobsError(String(e?.message || e))
    }
  }

  function priorityFlagLabel(flag) {
    const key = String(flag || '').trim().toLowerCase()
    if (key === 'manual_only') return t.manualOnly || 'Manual Only'
    if (key === 'company_under_review') return t.companyUnderReview || 'Already under review at company'
    if (key === 'low_priority') return t.reviewLater || 'Review later'
    if (key === 'closed_no_longer_accepting') return t.closedStopApply || 'Closed / stop apply'
    if (key === 'onsite_only') return t.onsiteOnly || 'Onsite only'
    if (key === 'full_time_only') return t.fullTimeOnly || 'Full-time only'
    if (key === 'part_time_only') return t.partTimeOnly || 'Part-time only'
    if (key === 'contract_only') return t.contractOnly || 'Contract only'
    if (key === 'internship_only') return t.internshipOnly || 'Internship only'
    return t.standardFlow || 'Standard flow'
  }

  function priorityFlagDescription(flag, scope = 'job') {
    const key = String(flag || '').trim().toLowerCase()
    if (key === 'manual_only') return 'Do not auto-apply. Keep for manual review only.'
    if (key === 'company_under_review') return 'Another application at this company is already under review. Push these jobs down and do not apply again for now.'
    if (key === 'low_priority') return 'Keep visible, but push lower in the queue for later review.'
    if (key === 'closed_no_longer_accepting') return 'Treat as closed and stop applying.'
    if (key === 'onsite_only') return 'Mark as not acceptable because this job requires onsite work.'
    if (key === 'full_time_only') return 'Mark as not acceptable because this job is full-time only.'
    if (key === 'part_time_only') return 'Mark as not acceptable because this job is part-time only.'
    if (key === 'contract_only') return 'Mark as not acceptable because this job is contract-only.'
    if (key === 'internship_only') return 'Mark as not acceptable because this job is internship-only.'
    return scope === 'company'
      ? (t.companyRuleDesc || 'Use as default for all jobs from this company.')
      : (t.jobRuleDesc || 'Use for one specific JD.')
  }

  async function updateJobPriority(detailJob, priorityFlag) {
    const jobId = Number(detailJob?.id || 0)
    if (!jobId) return
    const currentNote = String(detailJob?.job_priority_note || '').trim()
    const note = priorityFlag
      ? (window.prompt(t.priorityNote || 'Priority Note', currentNote) ?? currentNote)
      : ''
    setJobsError('')
    try {
      const res = await api.updateJobPriority(jobId, { priority_flag: priorityFlag, note: note || '' })
      const item = res?.item
      if (item) {
        setDetail(item)
        setItems((prev) => prev.map((row) => (Number(row.id) === jobId ? { ...row, ...item } : row)))
      }
      setReloadToken((n) => n + 1)
    } catch (e) {
      setJobsError(String(e?.message || e))
    }
  }

  async function updateCompanyPriority(detailJob, priorityFlag) {
    const companyName = String(detailJob?.company || '').trim()
    if (!companyName) return
    const currentNote = String(detailJob?.company_priority_note || '').trim()
    const note = priorityFlag
      ? (window.prompt(t.priorityNote || 'Priority Note', currentNote) ?? currentNote)
      : ''
    setJobsError('')
    try {
      await api.updateCompanyPriority({ company_name: companyName, priority_flag: priorityFlag, note: note || '' })
      const refreshed = await api.jobDetail(Number(detailJob.id), filters.constraint_mode || 'medium')
      setDetail(refreshed)
      setItems((prev) => prev.map((row) => {
        if (String(row.company || '').trim().toLowerCase() !== companyName.toLowerCase()) return row
        if (Number(row.id) === Number(refreshed.id)) return { ...row, ...refreshed }
        return {
          ...row,
          company_priority_flag: refreshed.company_priority_flag,
          company_priority_note: refreshed.company_priority_note,
          effective_priority_flag: String(row.job_priority_flag || '').trim() || refreshed.company_priority_flag,
          effective_priority_note: String(row.job_priority_flag || '').trim() ? row.job_priority_note : refreshed.company_priority_note,
        }
      }))
      setReloadToken((n) => n + 1)
    } catch (e) {
      setJobsError(String(e?.message || e))
    }
  }

  async function markJobAppliedManual(detailJob) {
    const jobId = Number(detailJob?.id || 0)
    if (!jobId) return
    setJobsError('')
    try {
      const res = await api.markJobAppliedManual(jobId, {})
      const item = res?.item
      if (item) {
        setDetail(item)
        setItems((prev) => prev.map((row) => (Number(row.id) === jobId ? { ...row, ...item } : row)))
      }
      setReloadToken((n) => n + 1)
    } catch (e) {
      setJobsError(String(e?.message || e))
    }
  }

  async function copyToClipboard(value) {
    const text = String(value || '').trim()
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
    } catch (e) {
      setJobsError(String(e?.message || e))
    }
  }

  async function generateCvForJob(jobId) {
    const selectedIds = Array.from(new Set((selectedJobIds || []).map((x) => Number(x)).filter((x) => Number.isFinite(x) && x > 0)))
    if (selectedIds.length > 1 && selectedIds.includes(Number(jobId)) && selectedCvState === 'missing') {
      await generateCvForSelected(selectedIds)
      return
    }
    setCvBusyJobId(jobId)
    setCvBusy(true)
    setJobsError('')
    try {
      const res = await api.rewriteRenderCvFromJob(jobId, {
        cv_master_path: 'input/full_doc_stlye.txt',
        guide_path: 'CV_REWRITE_STRICT_GUIDE.md',
        user_prompt: 'Bay gio hay dua vao [full_doc_stlye.txt](input/full_doc_stlye.txt) + JD lay tu DB theo job_id dang chon, cung voi [CV_REWRITE_STRICT_GUIDE.md](CV_REWRITE_STRICT_GUIDE.md), va thuc hien cac cong viec trong guide.',
        llm_model: 'qwen2.5:1.5b-instruct',
        temperature: 0.2,
        render_docx: true,
        render_pdf: true,
        run_fit_report: true,
      })
      setGeneratedCvItems((prev) => {
        const next = [...prev.filter((x) => x.job_id !== res.job_id), res]
        return next.slice(-20)
      })
      {
        const persistedPath = res.pdf_path || res.docx_path || res.cv_path || ''
        if (persistedPath) {
          setItems((prev) => prev.map((x) => (
            Number(x.id) === Number(jobId)
              ? { ...x, has_cv: 1, cv_source_path: persistedPath }
              : x
          )))
        }
      }
      setReloadToken((n) => n + 1)
    } catch (e) {
      setJobsError(String(e?.message || e))
    } finally {
      setCvBusy(false)
      setCvBusyJobId(null)
    }
  }

  async function generateCvForSelected(explicitJobIds = null) {
    const jobIds = Array.from(
      new Set((explicitJobIds || selectedJobIds || []).map((x) => Number(x)).filter((x) => Number.isFinite(x) && x > 0)),
    )
    if (!jobIds.length) return
    setCvBusyBatch(true)
    setCvBusy(true)
    setJobsError('')
    try {
      const res = await api.rewriteRenderCvFromJobs({
        job_ids: jobIds,
        cv_master_path: 'input/full_doc_stlye.txt',
        guide_path: 'CV_REWRITE_STRICT_GUIDE.md',
        user_prompt: 'Bay gio hay dua vao [full_doc_stlye.txt](input/full_doc_stlye.txt) + JD lay tu DB theo tung job_id duoc chon, cung voi [CV_REWRITE_STRICT_GUIDE.md](CV_REWRITE_STRICT_GUIDE.md), va thuc hien cac cong viec trong guide.',
        llm_model: 'qwen2.5:1.5b-instruct',
        temperature: 0.2,
        render_docx: true,
        render_pdf: true,
        run_fit_report: true,
      })
      setGeneratedCvItems((prev) => {
        const incoming = res.results || []
        const map = new Map(prev.map((x) => [x.job_id, x]))
        incoming.forEach((x) => map.set(x.job_id, x))
        return Array.from(map.values()).slice(-50)
      })
      setItems((prev) => {
        const byId = new Map((res.results || []).map((x) => [Number(x.job_id), (x.pdf_path || x.docx_path || x.cv_path || '')]))
        return prev.map((x) => {
          const p = byId.get(Number(x.id))
          if (!p) return x
          return { ...x, has_cv: 1, cv_source_path: p }
        })
      })
      const okCount = (res.results || []).length
      const errCount = (res.errors || []).length
      setSelectedJobIds([])
      setReloadToken((n) => n + 1)
      if (okCount === 0 && errCount > 0) {
        setJobsError(`No CV generated. ${errCount} job(s) failed.`)
      }
      if (errCount > 0) setJobsError(`Generated ${okCount} CV(s), ${errCount} failed.`)
    } catch (e) {
      setJobsError(String(e?.message || e))
    } finally {
      setCvBusy(false)
      setCvBusyBatch(false)
      setCvBusyJobId(null)
    }
  }

  async function runEvaluateFit() {
    setFitBusy(true)
    setFitInfo('')
    try {
      const mode = filters.constraint_mode || 'medium'
      const res = await api.evaluateFit({
        cv_path: 'input/full_doc_stlye.txt',
        stage: 'all',
        limit: 0,
        constraint_mode: mode,
        posted_within_days: Math.max(0, Number(filters.posted_within_days) || 0),
        sort_by: filters.sort_by || 'posted_date_desc',
      })
      setFitInfo(`evaluated=${res.evaluated || 0}`)
      setReloadToken((n) => n + 1)
    } finally {
      setFitBusy(false)
    }
  }

  const limitNum = Number(filters.limit) || 50
  const offsetNum = Number(filters.offset) || 0
  const page = Math.floor(offsetNum / limitNum) + 1
  const totalPages = Math.max(1, Math.ceil(total / limitNum))
  const countryOptions = countries.map((c) => ({ label: c, value: c }))
  const programmingLanguageOptions = (programmingLanguages || []).map((lang) => ({ label: lang, value: lang }))
  const rowsSorted = useMemo(() => sortRows(items, sort), [items, sort])
  const selectedSet = useMemo(() => new Set(selectedJobIds), [selectedJobIds])
  const generatedCvMap = useMemo(
    () => new Map((generatedCvItems || []).map((x) => [Number(x.job_id), x])),
    [generatedCvItems],
  )
  function cvItemFromPath(job, pathValue) {
    const sourcePath = String(pathValue || job?.cv_source_path || '')
    const sourceLower = sourcePath.toLowerCase()
    const pdfPath = String(job?.generated_pdf_path || (sourceLower.endsWith('.pdf') ? sourcePath : ''))
    const docxPath = String(job?.generated_docx_path || (sourceLower.endsWith('.docx') ? sourcePath : ''))
    const cvTextPath = String(job?.generated_cv_text_path || (sourceLower.endsWith('.txt') ? sourcePath : ''))
    if (!pdfPath && !docxPath && !cvTextPath && !String(job?.cover_letter_path || '').trim() && Number(job?.has_cv || 0) !== 1) return null
    return {
      job_id: Number(job?.id || 0),
      title: job?.title || '',
      pdf_path: pdfPath,
      docx_path: docxPath,
      cv_path: cvTextPath,
      portfolio_path: String(job?.portfolio_path || ''),
      video_path: String(job?.generated_video_path || ''),
      cover_letter_path: String(job?.cover_letter_path || ''),
      cover_letter_docx_path: String(job?.cover_letter_docx_path || job?.generated_cover_letter_docx_path || ''),
      cover_letter_pdf_path: String(job?.cover_letter_pdf_path || job?.generated_cover_letter_pdf_path || ''),
      headline: String(job?.generated_headline || ''),
      summary: String(job?.generated_summary || ''),
      experience_summary: String(job?.generated_experience_summary || ''),
      llm_backend: String(job?.generated_llm_backend || ''),
      llm_model: String(job?.generated_llm_model || job?.llm_model || ''),
      llm_usage: job?.generated_llm_usage || {},
      cv_text: '',
    }
  }
  function getCvItemForJob(job) {
    return generatedCvMap.get(Number(job?.id)) || cvItemFromPath(job, job?.cv_source_path)
  }
  async function openCvPreview(job) {
    const jobId = Number(job?.id || job?.job_id || 0)
    if (!jobId) return
    setJobsError('')
    try {
      const refreshed = await api.jobCvPreview(jobId, filters.constraint_mode || 'medium')
      const previewItem = cvItemFromPath(refreshed, refreshed?.cv_source_path) || generatedCvMap.get(jobId) || getCvItemForJob(job)
      if (previewItem) setCvPreview(previewItem)
      setItems((prev) => prev.map((row) => (Number(row.id) === jobId ? { ...row, ...refreshed } : row)))
      if (detail && Number(detail.id) === jobId) setDetail(refreshed)
    } catch (e) {
      const fallback = getCvItemForJob(job)
      if (fallback) setCvPreview(fallback)
      setJobsError(String(e?.message || e))
    }
  }
  function isUploadableCvPath(value) {
    return /\.(pdf|docx|doc|rtf)$/i.test(String(value || '').trim())
  }
  function getApplyCvPathForJob(job) {
    const cvItem = getCvItemForJob(job)
    const candidates = [
      cvItem?.pdf_path,
      cvItem?.docx_path,
      cvItem?.cv_path,
      job?.cv_source_path,
    ]
    for (const raw of candidates) {
      const value = String(raw || '').trim()
      if (value && isUploadableCvPath(value)) return value
    }
    return ''
  }
  function hasUploadableCvForJob(job) {
    return Boolean(getApplyCvPathForJob(job))
  }
  function isApplyCompletedByAutomation(job) {
    return String(job?.applied_source || '').trim().toLowerCase() === 'linkedin_easy_apply'
  }
  function isApplyCompletedManually(job) {
    return Number(job?.is_applied || 0) === 1 && String(job?.applied_source || '').trim().toLowerCase() === 'manual'
  }
  function isManualReviewJob(job) {
    return Number(job?.manual_review_required || 0) === 1
  }
  function getEffectivePriorityFlag(job) {
    return String(job?.effective_priority_flag || '').trim().toLowerCase()
  }
  function isManualOnlyJob(job) {
    return getEffectivePriorityFlag(job) === 'manual_only'
  }
  function isRejectedJob(job) {
    return [
      'manual_only',
      'company_under_review',
      'closed_no_longer_accepting',
      'onsite_only',
      'full_time_only',
      'part_time_only',
      'contract_only',
      'internship_only',
    ].includes(getEffectivePriorityFlag(job))
  }
  function isClosedJob(job) {
    return getEffectivePriorityFlag(job) === 'closed_no_longer_accepting'
  }
  function detailProgrammingLanguage(detail) {
    const primary = String(detail?.programming_language || '').trim()
    if (primary) return primary
    const items = Array.isArray(detail?.programming_languages) ? detail.programming_languages.map((x) => String(x || '').trim()).filter(Boolean) : []
    return items.join(', ')
  }
  function detailPostedText(detail) {
    return String(detail?.posted_time || detail?.latest_posted_time || '').trim()
  }
  function detailResponseText(detail) {
    return String(detail?.response_status || detail?.application_status || detail?.response_note || '').trim()
  }
  const showAppliedDate = forceAppliedView || String(filters.stage || '') === 'applied'
  function jobRowStyle(job) {
    const effectiveFlag = getEffectivePriorityFlag(job)
    if (effectiveFlag === 'closed_no_longer_accepting') return { backgroundColor: '#ead7d7', opacity: 0.82 }
    if (effectiveFlag === 'manual_only') return { backgroundColor: '#f8d7da' }
    if (effectiveFlag === 'company_under_review') return { backgroundColor: '#e8eefc' }
    if (effectiveFlag === 'onsite_only') return { backgroundColor: '#fbe4d5' }
    if (effectiveFlag === 'full_time_only') return { backgroundColor: '#f9e2d2' }
    if (effectiveFlag === 'part_time_only') return { backgroundColor: '#f7ead8' }
    if (effectiveFlag === 'contract_only') return { backgroundColor: '#f8e7dc' }
    if (effectiveFlag === 'internship_only') return { backgroundColor: '#f6e0d8' }
    if (effectiveFlag === 'low_priority') return { backgroundColor: '#fde2e4' }
    if (!isManualReviewJob(job)) return undefined
    return { backgroundColor: '#fff3cd' }
  }
  useEffect(() => {
    let cancelled = false
    async function loadCvText() {
      if (!cvPreview) {
        setCvPreviewText('')
        setCvPreviewTextLoading(false)
        return
      }
      if (String(cvPreview.cv_text || '').trim()) {
        setCvPreviewText(String(cvPreview.cv_text || ''))
        setCvPreviewTextLoading(false)
        return
      }
      if (!String(cvPreview.cv_path || '').trim()) {
        setCvPreviewText('')
        setCvPreviewTextLoading(false)
        return
      }
      setCvPreviewTextLoading(true)
      try {
        const res = await api.fileText(cvPreview.cv_path)
        if (!cancelled) setCvPreviewText(String(res.content || ''))
      } catch {
        if (!cancelled) setCvPreviewText('')
      } finally {
        if (!cancelled) setCvPreviewTextLoading(false)
      }
    }
    loadCvText()
    return () => {
      cancelled = true
    }
  }, [cvPreview])
  useEffect(() => {
    let cancelled = false
    async function loadCoverLetterText() {
      if (!cvPreview || !String(cvPreview.cover_letter_path || '').trim()) {
        setCoverLetterText('')
        setCoverLetterTextLoading(false)
        return
      }
      setCoverLetterTextLoading(true)
      try {
        const res = await api.fileText(cvPreview.cover_letter_path)
        if (!cancelled) setCoverLetterText(String(res.content || ''))
      } catch {
        if (!cancelled) setCoverLetterText('')
      } finally {
        if (!cancelled) setCoverLetterTextLoading(false)
      }
    }
    loadCoverLetterText()
    return () => {
      cancelled = true
    }
  }, [cvPreview])
  function cvStateForJob(job) {
    return hasUploadableCvForJob(job) ? 'ready' : 'missing'
  }
  const itemsById = useMemo(() => new Map((items || []).map((x) => [Number(x.id), x])), [items])
  const selectedCvState = useMemo(() => {
    for (const id of selectedJobIds) {
      const row = itemsById.get(Number(id))
      if (row) return cvStateForJob(row)
    }
    return null
  }, [selectedJobIds, itemsById, generatedCvMap])
  const selectableRowsOnPage = useMemo(() => {
    const mode = selectedCvState || (rowsSorted[0] ? cvStateForJob(rowsSorted[0]) : null)
    if (!mode) return []
    return rowsSorted.filter((j) => cvStateForJob(j) === mode)
  }, [rowsSorted, selectedCvState, generatedCvMap])
  const allOnPageSelected = selectableRowsOnPage.length > 0 && selectableRowsOnPage.every((j) => selectedSet.has(j.id))
  const canGenerateSelected = selectedJobIds.length > 0 && selectedCvState === 'missing'
  const onSort = (key) => setSort((prev) => ({ key, dir: prev.key === key && prev.dir === 'asc' ? 'desc' : 'asc' }))

  async function deleteJobs(jobIds) {
    const ids = Array.from(new Set((jobIds || []).map((x) => Number(x)).filter((x) => Number.isFinite(x) && x > 0)))
    if (!ids.length) return
    if (!window.confirm(`Delete ${ids.length} job(s)?`)) return
    setDeleteBusy(true)
    setJobsError('')
    try {
      await api.deleteJobs(ids)
      const removed = new Set(ids)
      setItems((prev) => prev.filter((x) => !removed.has(Number(x.id))))
      setSelectedJobIds((prev) => prev.filter((id) => !removed.has(Number(id))))
      setGeneratedCvItems((prev) => prev.filter((x) => !removed.has(Number(x.job_id))))
      setTotal((prev) => Math.max(0, Number(prev || 0) - ids.length))
      if (detail && removed.has(Number(detail.id))) setDetail(null)
      if (cvPreview && removed.has(Number(cvPreview.job_id))) setCvPreview(null)
      setReloadToken((n) => n + 1)
    } catch (e) {
      setJobsError(String(e?.message || e))
    } finally {
      setDeleteBusy(false)
    }
  }

  async function openApplyModal() {
    if (!selectedJobIds.length) return
    setJobsError('')
    const ids = Array.from(new Set((selectedJobIds || []).map((x) => Number(x)).filter((x) => Number.isFinite(x) && x > 0)))
    applyCvLogger.info('open_modal_start', { selected_jobs: ids.length, sample_job_ids: ids.slice(0, 10) })
    try {
      const res = await api.cvFiles('pdf,docx')
      const preferred = ids
        .map((id) => getApplyCvPathForJob(itemsById.get(Number(id))))
        .filter(Boolean)
      const items = Array.isArray(res.items) ? res.items : []
      const known = new Set(items.map((x) => String(x?.path || '').trim()).filter(Boolean))
      const mergedItems = [
        ...preferred.filter((x) => !known.has(String(x || '').trim())).map((path) => ({ path, name: path.split(/[/\\]/).pop() || path })),
        ...items,
      ]
      applyCvLogger.info('cv_files_loaded', { total_files: mergedItems.length, sample_files: mergedItems.slice(0, 5).map((x) => x?.path || x?.name || '') })
      setCvFileOptions(mergedItems)
      const defaultSelected = Array.from(new Set(preferred.length ? preferred : items.slice(0, 1).map((x) => x.path)))
      setSelectedApplyCvPaths(defaultSelected)
      setApplyModalOpen(true)
      applyCvLogger.info('open_modal_success', { default_selected_cv_paths: defaultSelected })
    } catch (e) {
      applyCvLogger.error('open_modal_failed', { message: String(e?.message || e) })
      setJobsError(String(e?.message || e))
    }
  }

  function toggleApplyCvPath(pathValue) {
    const path = String(pathValue || '')
    if (!path) return
    setSelectedApplyCvPaths((prev) => {
      const current = new Set(prev || [])
      if (current.has(path)) current.delete(path)
      else current.add(path)
      return Array.from(current)
    })
  }

  async function submitApplySelected() {
    const ids = Array.from(new Set((selectedJobIds || []).map((x) => Number(x)).filter((x) => Number.isFinite(x) && x > 0)))
    const cvPaths = Array.from(new Set((selectedApplyCvPaths || []).map((x) => String(x || '').trim()).filter(Boolean)))
    if (!ids.length) return
    setApplyBusy(true)
    setApplyBusyJobId(null)
    setJobsError('')
    applyCvLogger.info('submit_selected_start', {
      selected_jobs: ids.length,
      selected_cvs: cvPaths.length,
      sample_job_ids: ids.slice(0, 10),
      sample_cv_paths: cvPaths.slice(0, 5),
    })
    try {
      const result = await api.linkedinApply({
        job_ids: ids,
        cv_paths: cvPaths,
        dry_run: false,
      })
      if (result?.ok === false) {
        const statuses = Array.isArray(result?.statuses) ? result.statuses.join(', ') : ''
        const diagnostics = Array.isArray(result?.diagnostics) ? result.diagnostics.join(' | ') : ''
        const message = `Apply not completed: ${statuses || 'unknown'}${diagnostics ? ` | ${diagnostics}` : ''}`
        applyCvLogger.warn('submit_selected_non_success', {
          run_id: result?.run_id,
          returncode: result?.returncode,
          statuses: result?.statuses,
          diagnostics: result?.diagnostics,
        })
        setJobsError(message)
        return
      }
      applyCvLogger.info('submit_selected_success', {
        run_id: result?.run_id,
        returncode: result?.returncode,
        jobs: ids.length,
        cvs: cvPaths.length,
      })
      setApplyModalOpen(false)
      setReloadToken((n) => n + 1)
    } catch (e) {
      applyCvLogger.error('submit_selected_failed', {
        message: String(e?.message || e),
        selected_jobs: ids.length,
        selected_cvs: cvPaths.length,
      })
      setJobsError(String(e?.message || e))
    } finally {
      setApplyBusy(false)
    }
  }

  async function applyForJob(job) {
    const jobId = Number(job?.id)
    const cvPath = getApplyCvPathForJob(job)
    if (!Number.isFinite(jobId) || jobId <= 0) return
    setApplyBusy(true)
    setApplyBusyJobId(jobId)
    setJobsError('')
    applyCvLogger.info('single_apply_start', { job_id: jobId, cv_path: cvPath })
    try {
      const result = await api.linkedinApply({
        job_ids: [jobId],
        cv_paths: [cvPath],
        dry_run: false,
      })
      if (result?.ok === false) {
        const statuses = Array.isArray(result?.statuses) ? result.statuses.join(', ') : ''
        const diagnostics = Array.isArray(result?.diagnostics) ? result.diagnostics.join(' | ') : ''
        const message = `Apply not completed: ${statuses || 'unknown'}${diagnostics ? ` | ${diagnostics}` : ''}`
        applyCvLogger.warn('single_apply_non_success', {
          job_id: jobId,
          run_id: result?.run_id,
          returncode: result?.returncode,
          statuses: result?.statuses,
          diagnostics: result?.diagnostics,
        })
        setJobsError(message)
        return
      }
      applyCvLogger.info('single_apply_success', {
        job_id: jobId,
        run_id: result?.run_id,
        returncode: result?.returncode,
      })
      setReloadToken((n) => n + 1)
    } catch (e) {
      applyCvLogger.error('single_apply_failed', { job_id: jobId, cv_path: cvPath, message: String(e?.message || e) })
      setJobsError(String(e?.message || e))
    } finally {
      setApplyBusy(false)
      setApplyBusyJobId(null)
    }
  }

  return (
    <div className="grid single">
      <div className="card">
        <div className="jobs-head">
          <h3>{tabTitle || t.jobs} ({total})</h3>
        </div>
        <div className="jobs-filter-panel">
          <div className="jobs-filter-grid">
            <label className="jobs-filter-field jobs-filter-search">
              <span>{t.searchPlaceholder || 'Search title/company'}</span>
              <input placeholder={t.searchPlaceholder} value={filters.search} onChange={(e) => patchFilters({ search: e.target.value, offset: '0' })} />
            </label>
            <label className="jobs-filter-field">
              <span>{t.country}</span>
              <CheckboxMultiSelect label={t.country} options={countryOptions} groups={countryGroups} selected={filters.countries} onChange={(v) => patchFilters({ countries: v, offset: '0' })} t={t} applyMode />
            </label>
            <label className="jobs-filter-field">
              <span>{t.workModel || 'Work Model'}</span>
              <CheckboxMultiSelect label={t.workModel || 'Work Model'} options={WORK_MODEL_OPTIONS} selected={filters.work_models} onChange={(v) => patchFilters({ work_models: v, offset: '0' })} t={t} applyMode />
            </label>
            <label className="jobs-filter-field">
              <span>{t.employmentType || 'Employment Type'}</span>
              <CheckboxMultiSelect label={t.employmentType || 'Employment Type'} options={EMPLOYMENT_TYPE_OPTIONS} selected={filters.employment_types} onChange={(v) => patchFilters({ employment_types: v, offset: '0' })} t={t} applyMode />
            </label>
            <label className="jobs-filter-field">
              <span>{t.programLanguage}</span>
              <CheckboxMultiSelect label={t.programLanguage} options={programmingLanguageOptions} groups={programmingLanguageGroups} selected={filters.programming_languages} onChange={(v) => patchFilters({ programming_languages: v, offset: '0' })} t={t} includeGroupValue={false} applyMode />
            </label>
            <label className="jobs-filter-field jobs-filter-compact">
              <span>{t.postedWithinDays}</span>
              <input
                type="number"
                min="0"
                placeholder={t.postedWithinDays}
                value={filters.posted_within_days}
                onChange={(e) => patchFilters({ posted_within_days: e.target.value, offset: '0' })}
              />
            </label>
            <label className="jobs-filter-field jobs-filter-compact">
              <span>{t.postedDate}</span>
              <select
                value={String(filters.sort_by || 'posted_date_desc')}
                onChange={(e) => patchFilters({ sort_by: e.target.value, offset: '0' })}
              >
                <option value="posted_date_desc">{`${t.postedDate || 'Posted'} ${t.sortDesc || 'Desc'}`}</option>
                <option value="posted_date_asc">{`${t.postedDate || 'Posted'} ${t.sortAsc || 'Asc'}`}</option>
              </select>
            </label>
            <label className="jobs-filter-field jobs-filter-compact">
              <span>{t.filter || 'Filter'}</span>
              <select value={filters.stage} onChange={(e) => patchFilters({ stage: e.target.value, offset: '0' })} disabled={forceAppliedView}>
                <option value="all">{t.all}</option>
                <option value="filtered">{t.filtered}</option>
                <option value="applied">{t.applied}</option>
              </select>
            </label>
            <label className="jobs-filter-field jobs-filter-compact">
              <span>{t.cvGenerated || 'CV generated'}</span>
              <select value={String(filters.has_cv)} onChange={(e) => patchFilters({ has_cv: Number(e.target.value), offset: '0' })}>
                <option value="-1">{t.all || 'All'}</option>
                <option value="1">{t.cvGenerated || 'CV generated'}</option>
                <option value="0">No CV</option>
              </select>
            </label>
            <label className="jobs-filter-field jobs-filter-compact">
              <span>{t.easyApply || 'Easy Apply'}</span>
              <select value={String(filters.easy_apply ?? -1)} onChange={(e) => patchFilters({ easy_apply: Number(e.target.value), offset: '0' })}>
                <option value="-1">{t.all || 'All'}</option>
                <option value="1">{t.yes || 'Yes'}</option>
                <option value="0">{t.no || 'No'}</option>
              </select>
            </label>
          </div>
          <div className="filters jobs-toolbar">
            <label className="muted">
              {t.constraintMode || 'Constraint Mode'}:{' '}
              <select
                value={filters.constraint_mode || 'medium'}
                onChange={(e) => {
                  const mode = e.target.value
                  patchFilters({ constraint_mode: mode, offset: '0' })
                }}
              >
                <option value="hard">{t.hard || 'Hard'}</option>
                <option value="medium">{t.medium || 'Medium'}</option>
                <option value="soft">{t.soft || 'Soft'}</option>
              </select>
            </label>
            <button disabled={fitBusy} onClick={runEvaluateFit}>{fitBusy ? t.evaluating : t.evaluateFit}</button>
            <button disabled={!canGenerateSelected || cvBusy || deleteBusy} onClick={generateCvForSelected}>
              {cvBusyBatch ? (t.processingCv || 'Processing CV...') : (t.generateSelectedCv || 'Generate Selected CV')}
            </button>
            <button disabled={selectedJobIds.length === 0 || cvBusy || deleteBusy || applyBusy} onClick={openApplyModal}>
              {applyBusy ? (t.processingApply || 'Applying...') : (t.applySelected || 'Apply Selected')}
            </button>
            <button disabled={selectedJobIds.length === 0 || deleteBusy} onClick={() => deleteJobs(selectedJobIds)}>
              {deleteBusy ? `${t.delete || 'Delete'}...` : `${t.delete || 'Delete'} (${selectedJobIds.length})`}
            </button>
            <button onClick={clearAllFilters}>{t.clearAllFilters || 'Clear All Filters'}</button>
            {fitInfo && <span className="muted">{fitInfo}</span>}
            {selectedCvState && (
              <span className="muted">
                Selection mode: {selectedCvState === 'ready' ? 'CV ready only' : 'Generate CV only'}
              </span>
            )}
          </div>
        </div>
        {jobsError && <div className="error-text">{jobsError}</div>}
        {loading ? <p>{t.loading}</p> : (
          <>
          <div className="jobs-table-wrap">
          <table className="jobs-table">
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    title={t.selectAll || 'Select all'}
                    checked={allOnPageSelected}
                    disabled={selectableRowsOnPage.length === 0}
                    onChange={(e) => {
                      const mode = selectedCvState || (rowsSorted[0] ? cvStateForJob(rowsSorted[0]) : null)
                      const eligible = mode ? rowsSorted.filter((j) => cvStateForJob(j) === mode) : []
                      if (e.target.checked) {
                        setSelectedJobIds(Array.from(new Set([...selectedJobIds, ...eligible.map((j) => j.id)])))
                      } else {
                        const remove = new Set(eligible.map((j) => j.id))
                        setSelectedJobIds(selectedJobIds.filter((id) => !remove.has(id)))
                      }
                    }}
                  />
                </th>
                <SortTh label="ID" col="id" sort={sort} onSort={onSort} />
                <SortTh label="Title" col="title" sort={sort} onSort={onSort} />
                <SortTh label={t.company} col="company" sort={sort} onSort={onSort} />
                <SortTh label={t.postedDate} col="linkedin_posted_date" sort={sort} onSort={onSort} />
                {showAppliedDate ? <SortTh label={t.applyDate || 'Apply Date'} col="applied_last_seen_date" sort={sort} onSort={onSort} /> : null}
                <SortTh label={t.applied} col="is_applied" sort={sort} onSort={onSort} />
                <SortTh label={t.fitScore || 'Fit Score'} col="fit_score" sort={sort} onSort={onSort} />
                <th>{t.action || 'Action'}</th>
              </tr>
            </thead>
            <tbody>
              {rowsSorted.map((j) => (
                <tr key={j.id} style={jobRowStyle(j)}>
                    <td>
                      <input
                        type="checkbox"
                        checked={selectedSet.has(j.id)}
                        disabled={!selectedSet.has(j.id) && !!selectedCvState && cvStateForJob(j) !== selectedCvState}
                        onChange={(e) => {
                          if (e.target.checked) setSelectedJobIds(Array.from(new Set([...selectedJobIds, j.id])))
                          else setSelectedJobIds(selectedJobIds.filter((id) => id !== j.id))
                        }}
                      />
                    </td>
                    <td>{j.id}</td>
                    <td>
                      <button className="link-btn" onClick={() => openDetail(j.id)}>{j.title}</button>
                      {isManualReviewJob(j) ? (
                        <>
                          <div className="muted">{t.manualReview || 'Manual Review'}</div>
                          <div className="muted">{String(j.manual_review_note || '').slice(0, 140) || '-'}</div>
                        </>
                      ) : null}
                      {getEffectivePriorityFlag(j) ? (
                        <>
                          <div className="muted">{priorityFlagLabel(j.effective_priority_flag)}</div>
                          <div className="muted">{String(j.effective_priority_note || '').slice(0, 140) || '-'}</div>
                        </>
                      ) : null}
                    </td>
                    <td>{formatCompanyWithCountry(j)}</td>
                    <td>{j.linkedin_posted_date || '-'}</td>
                    {showAppliedDate ? <td>{j.applied_last_seen_date || '-'}</td> : null}
                    <td>{j.is_applied ? t.yes : t.no}</td>
                    <td title={String(j.main_issue || j.primary_issue_text || 'No main issue')}>
                      {j.fit_score || 0}
                    </td>
                    <td>
                      <div className="action-cell">
                        {getCvItemForJob(j) ? (
                          <>
                            <button onClick={() => openCvPreview(j)}>CV</button>
                            <button
                              onClick={() => applyForJob(j)}
                              disabled={cvBusy || deleteBusy || applyBusyJobId === j.id || isApplyCompletedByAutomation(j) || isRejectedJob(j)}
                            >
                              {applyBusyJobId === j.id ? (t.processingApply || 'Applying...') : (t.apply || 'Apply')}
                            </button>
                            <button
                              onClick={() => markJobAppliedManual(j)}
                              disabled={cvBusy || deleteBusy || applyBusyJobId === j.id || Number(j?.is_applied || 0) === 1}
                              className={isApplyCompletedManually(j) ? 'status-btn status-btn-manual-applied' : ''}
                            >
                              {isApplyCompletedManually(j) ? (t.manualApplied || 'Manual applied') : (t.markAppliedManual || 'Mark Applied Manual')}
                            </button>
                          </>
                        ) : (
                          <button
                            onClick={() => {
                              const ids = Array.from(new Set((selectedJobIds || []).map((x) => Number(x)).filter((x) => Number.isFinite(x) && x > 0)))
                              if (ids.length > 1 && ids.includes(Number(j.id)) && selectedCvState === 'missing') {
                                generateCvForSelected(ids)
                                return
                              }
                              generateCvForJob(j.id)
                            }}
                            disabled={cvBusy || deleteBusy}
                          >
                            {cvBusyJobId === j.id || (cvBusyBatch && selectedSet.has(j.id))
                              ? (t.processingCv || 'Processing CV...')
                              : ((selectedSet.has(j.id) && selectedSet.size > 1 && selectedCvState === 'missing')
                                ? (t.generateSelectedCv || 'Generate Selected CV')
                                : (t.generateCv || 'Generate CV'))}
                          </button>
                        )}
                        <button onClick={() => deleteJobs([j.id])} disabled={cvBusy || deleteBusy}>
                          {t.delete || 'Delete'}
                        </button>
                      </div>
                    </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          <div className="pager pager-bottom">
            <span>{t.showing} {total === 0 ? 0 : offsetNum + 1}-{Math.min(offsetNum + limitNum, total)} {t.of} {total} {t.records}</span>
            <span>{t.pageSize}</span>
            <select value={filters.limit} onChange={(e) => patchFilters({ limit: e.target.value, offset: '0' })}>
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>{size}</option>
              ))}
            </select>
            <button disabled={page <= 1} onClick={() => patchFilters({ offset: String(Math.max(0, offsetNum - limitNum)) })}>{t.prev}</button>
            <span>{t.page} {page}/{totalPages}</span>
            <button disabled={page >= totalPages} onClick={() => patchFilters({ offset: String(offsetNum + limitNum) })}>{t.next}</button>
            <ScrollTopButton onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })} />
          </div>
          </>
        )}
      </div>

      <Modal open={!!detail} onClose={() => setDetail(null)} title={`${t.details}: ${detail?.title || ''}`} t={t}>
        {detail && (
          <>
            <p><b>{t.company}:</b> {detail.company}</p>
            <p><b>{t.location}:</b> {detail.location}</p>
            <p><b>{t.workModel || 'Work Model'}:</b> {detail.work_model || '-'} | <b>{t.employmentType || 'Employment Type'}:</b> {detail.employment_type || '-'}</p>
            <p><b>{t.programLanguage}:</b> {detailProgrammingLanguage(detail) || '-'}</p>
            <p>
              <b>{t.linkedinLink}:</b>{' '}
              {(detail.job_url_final || detail.job_url) ? (
                <a href={detail.job_url_final || detail.job_url} target="_blank" rel="noreferrer">
                  {detail.job_url_final || detail.job_url}
                </a>
              ) : '-'}
            </p>
            <p><b>{t.postedDate}:</b> {detail.linkedin_posted_date || '-'} ({t.estimatedFromText})</p>
            <p><b>{t.postedTimeText}:</b> {detailPostedText(detail) || '-'}</p>
            <p><b>{t.applied}:</b> {detail.is_applied ? t.yes : t.no} | <b>{t.response}:</b> {detailResponseText(detail) || '-'}</p>
            {isManualReviewJob(detail) ? (
              <p><b>{t.manualReview || 'Manual Review'}:</b> {detail.manual_review_note || '-'}</p>
            ) : null}
            {getEffectivePriorityFlag(detail) ? (
              <p><b>{t.priorityFlag || 'Priority Flag'}:</b> {priorityFlagLabel(detail.effective_priority_flag)} | <b>{t.priorityNote || 'Priority Note'}:</b> {detail.effective_priority_note || '-'}</p>
            ) : null}
            <p><b>{t.fit}:</b> {detail.fit_score} ({detail.fit_status || t.notEvaluated})</p>
            {renderFitPrimaryIssue(detail) ? (
              <p className="fit-primary-issue">{renderFitPrimaryIssue(detail)}</p>
            ) : null}
            <p><b>{t.fitReason || 'Fit Reason'}:</b> {detail.fit_reason || '-'}</p>
            <p><b>{t.firstSeen}:</b> {detail.first_seen_date} | <b>{t.lastSeen}:</b> {detail.last_seen_date}</p>
            <div className="priority-panel">
              <div className="priority-panel-row">
                <div>
                  <div className="priority-panel-title">{t.jobRule || 'Job Rule'}</div>
                  <div className="muted">{t.jobRuleDesc || 'Use for one specific JD.'}</div>
                </div>
                <select
                  value={String(detail.job_priority_flag || '')}
                  onChange={(e) => updateJobPriority(detail, e.target.value)}
                >
                  <option value="">{t.jobOverride || 'No job override'}</option>
                  <option value="low_priority">{t.reviewLater || 'Review later'}</option>
                  <option value="manual_only">{t.manualOnly || 'Manual Only'}</option>
                  <option value="company_under_review">{t.companyUnderReview || 'Already under review at company'}</option>
                  <option value="onsite_only">{t.onsiteOnly || 'Onsite only'}</option>
                  <option value="full_time_only">{t.fullTimeOnly || 'Full-time only'}</option>
                  <option value="part_time_only">{t.partTimeOnly || 'Part-time only'}</option>
                  <option value="contract_only">{t.contractOnly || 'Contract only'}</option>
                  <option value="internship_only">{t.internshipOnly || 'Internship only'}</option>
                  <option value="closed_no_longer_accepting">{t.closedStopApply || 'Closed / stop apply'}</option>
                </select>
              </div>
              <div className="muted">{priorityFlagDescription(detail.job_priority_flag, 'job')}</div>
              <div className="priority-panel-row">
                <div>
                  <div className="priority-panel-title">{t.companyRule || 'Company Rule'}</div>
                  <div className="muted">{t.companyRuleDesc || 'Use as default for all jobs from this company.'}</div>
                </div>
                <select
                  value={String(detail.company_priority_flag || '')}
                  onChange={(e) => updateCompanyPriority(detail, e.target.value)}
                >
                  <option value="">{t.companyDefault || 'No company default'}</option>
                  <option value="low_priority">{t.reviewLater || 'Review later'}</option>
                  <option value="manual_only">{t.manualOnly || 'Manual Only'}</option>
                  <option value="company_under_review">{t.companyUnderReview || 'Already under review at company'}</option>
                  <option value="onsite_only">{t.onsiteOnly || 'Onsite only'}</option>
                  <option value="full_time_only">{t.fullTimeOnly || 'Full-time only'}</option>
                  <option value="part_time_only">{t.partTimeOnly || 'Part-time only'}</option>
                  <option value="contract_only">{t.contractOnly || 'Contract only'}</option>
                  <option value="internship_only">{t.internshipOnly || 'Internship only'}</option>
                </select>
              </div>
              <div className="muted">{priorityFlagDescription(detail.company_priority_flag, 'company')}</div>
              <div className="priority-effective">
                <b>{t.effectiveRule || 'Effective Rule'}:</b> {priorityFlagLabel(detail.effective_priority_flag)}
                {detail.effective_priority_note ? ` — ${detail.effective_priority_note}` : ''}
              </div>
              <div className="muted">{t.jobRuleHint || 'Job rule overrides company rule when both are set.'}</div>
            </div>
            <div className="filters">
              {(generatedCvMap.get(Number(detail.id)) || cvItemFromPath(detail, detail.cv_source_path)) ? (
                <>
                  <button onClick={() => openCvPreview(detail)}>CV</button>
                  <button
                    onClick={() => applyForJob(detail)}
                    disabled={cvBusy || applyBusyJobId === detail.id || isApplyCompletedByAutomation(detail) || isRejectedJob(detail)}
                  >
                    {applyBusyJobId === detail.id ? (t.processingApply || 'Applying...') : (t.apply || 'Apply')}
                  </button>
                </>
              ) : (
                <button
                  onClick={() => {
                    const ids = Array.from(new Set((selectedJobIds || []).map((x) => Number(x)).filter((x) => Number.isFinite(x) && x > 0)))
                    if (ids.length > 1 && ids.includes(Number(detail.id)) && selectedCvState === 'missing') {
                      generateCvForSelected(ids)
                      return
                    }
                    generateCvForJob(detail.id)
                  }}
                  disabled={cvBusy}
                >
                  {cvBusyJobId === detail.id || cvBusyBatch ? (t.processingCv || 'Processing CV...') : (t.generateCv || 'Generate CV')}
                </button>
              )}
              <button
                onClick={() => markJobAppliedManual(detail)}
                disabled={cvBusy || applyBusyJobId === detail.id || Number(detail?.is_applied || 0) === 1}
                className={isApplyCompletedManually(detail) ? 'status-btn status-btn-manual-applied' : ''}
              >
                {isApplyCompletedManually(detail) ? (t.manualApplied || 'Manual applied') : (t.markAppliedManual || 'Mark Applied Manual')}
              </button>
            </div>
            <div className="code">{(detail.jd_text || detail.latest_payload?.jd || '') || t.noJdText}</div>
          </>
        )}
      </Modal>
      <Modal open={applyModalOpen} onClose={() => { if (!applyBusy) setApplyModalOpen(false) }} title={t.applySelected || 'Apply Selected'} t={t}>
        <div className="filters">
          <div className="muted">{t.selectCvFiles || 'Select CV files'} ({selectedApplyCvPaths.length})</div>
        </div>
        {cvFileOptions.length === 0 ? (
          <div className="muted">No CV files found in documents (.pdf/.docx).</div>
        ) : (
          <div className="cv-file-list">
            {cvFileOptions.map((item) => {
              const checked = selectedApplyCvPaths.includes(item.path)
              return (
                <label key={item.path} className="cv-file-item">
                  <input type="checkbox" checked={checked} onChange={() => toggleApplyCvPath(item.path)} disabled={applyBusy} />
                  <span>{item.name}</span>
                </label>
              )
            })}
          </div>
        )}
        <div className="filters">
          <button onClick={submitApplySelected} disabled={applyBusy || selectedJobIds.length === 0}>
            {applyBusy ? (t.processingApply || 'Applying...') : (t.applySelected || 'Apply Selected')}
          </button>
        </div>
      </Modal>
      <Modal open={!!cvPreview} onClose={() => setCvPreview(null)} title={`${t.previewCv || 'Preview CV'}: ${cvPreview?.title || cvPreview?.job_id || ''}`} t={t}>
        {cvPreview && (
          <>
              <p><b>PDF Path:</b> {cvPreview.pdf_path || '-'} {cvPreview.pdf_path ? <button onClick={() => copyToClipboard(cvPreview.pdf_path)}>Copy</button> : null}</p>
              <p><b>DOCX Path:</b> {cvPreview.docx_path || '-'} {cvPreview.docx_path ? <button onClick={() => copyToClipboard(cvPreview.docx_path)}>Copy</button> : null}</p>
              <p><b>TXT Path:</b> {cvPreview.cv_path || '-'} {cvPreview.cv_path ? <button onClick={() => copyToClipboard(cvPreview.cv_path)}>Copy</button> : null}</p>
              <p><b>Portfolio PDF:</b> {cvPreview.portfolio_path || '-'} {cvPreview.portfolio_path ? <><a href={api.fileContentUrl(cvPreview.portfolio_path)} target="_blank" rel="noreferrer">Open</a> <button onClick={() => copyToClipboard(cvPreview.portfolio_path)}>Copy</button></> : null}</p>
              <p><b>Video Path:</b> {cvPreview.video_path || '-'} {cvPreview.video_path ? <button onClick={() => copyToClipboard(cvPreview.video_path)}>Copy</button> : null}</p>
              <p><b>LLM Backend:</b> {cvPreview.llm_backend || cvPreview.llm_usage?.llm_backend || '-'}</p>
              <p><b>LLM Model:</b> {cvPreview.llm_model || '-'}</p>
              <p><b>LLM Status:</b> {cvPreview.llm_usage?.fallback ? `Fallback (${cvPreview.llm_usage?.fallback_reason || 'unknown'})` : (cvPreview.llm_backend === 'gateway_ollama_chat' ? 'Gateway -> Ollama' : 'Gateway')}</p>
              <p><b>Cover Letter TXT Path:</b> {cvPreview.cover_letter_path || '-'} {cvPreview.cover_letter_path ? <button onClick={() => copyToClipboard(cvPreview.cover_letter_path)}>Copy</button> : null}</p>
              <p><b>Cover Letter DOCX Path:</b> {cvPreview.cover_letter_docx_path || '-'} {cvPreview.cover_letter_docx_path ? <><a href={api.fileContentUrl(cvPreview.cover_letter_docx_path)} target="_blank" rel="noreferrer">Open</a> <button onClick={() => copyToClipboard(cvPreview.cover_letter_docx_path)}>Copy</button></> : null}</p>
              <p><b>Cover Letter PDF Path:</b> {cvPreview.cover_letter_pdf_path || '-'} {cvPreview.cover_letter_pdf_path ? <><a href={api.fileContentUrl(cvPreview.cover_letter_pdf_path)} target="_blank" rel="noreferrer">Open</a> <button onClick={() => copyToClipboard(cvPreview.cover_letter_pdf_path)}>Copy</button></> : null}</p>
              <p><b>Cover Letter:</b></p>
              {coverLetterTextLoading ? (
                <p className="muted">{t.loading || 'Loading...'}</p>
              ) : coverLetterText ? (
                <div className="code">{coverLetterText}</div>
            ) : (
              <p>-</p>
            )}
            <p><b>Headline:</b> {cvPreview.headline || '-'}</p>
            <p><b>Summary:</b> {cvPreview.summary || '-'}</p>
            <p><b>Experience Summary:</b> {cvPreview.experience_summary || '-'}</p>
            {cvPreviewTextLoading ? (
              <p className="muted">{t.loading || 'Loading...'}</p>
            ) : (cvPreviewText || cvPreview.cv_text) ? (
              <div
                className="cv-rich-view"
                dangerouslySetInnerHTML={{ __html: cvTaggedTextToHtml(cvPreviewText || cvPreview.cv_text || '') }}
              />
            ) : cvPreview.pdf_path ? (
              <>
                <div className="filters">
                  <a href={api.fileContentUrl(cvPreview.pdf_path)} target="_blank" rel="noreferrer">
                    Open PDF
                  </a>
                </div>
                <object
                  className="pdf-frame"
                  data={api.fileContentUrl(cvPreview.pdf_path)}
                  type="application/pdf"
                >
                  <iframe
                    className="pdf-frame"
                    src={api.fileContentUrl(cvPreview.pdf_path)}
                    title={`cv-pdf-${cvPreview.job_id || 'preview'}`}
                  />
                </object>
              </>
            ) : (
              <div className="code">{cvPreview.cv_text || '-'}</div>
            )}
          </>
        )}
      </Modal>
    </div>
  )
}

function AnalyticsTab({ countries, countryGroups, t, onOpenJobs }) {
  const analyticsView = useMemo(() => readStoredState(ANALYTICS_STATE_KEY, {}), [])
  const [filters, setFilters] = useState(() => ({ countries: [], company: '', min_reposts: '1', limit: '200', ...(analyticsView?.filters || {}) }))
  const [rows, setRows] = useState([])
  const [sort, setSort] = useState({ key: 'repost_count', dir: 'desc' })
  const [page, setPage] = useState(() => Number(analyticsView?.page) || 1)
  const [pageSize, setPageSize] = useState(() => Number(analyticsView?.pageSize) || 50)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const countryOptions = countries.map((c) => ({ label: c, value: c }))
  const rowsSorted = useMemo(() => sortRows(rows, sort), [rows, sort])
  const pg = useMemo(() => paginateRows(rowsSorted, page, pageSize), [rowsSorted, page, pageSize])
  const onSort = (key) => setSort((prev) => ({ key, dir: prev.key === key && prev.dir === 'asc' ? 'desc' : 'asc' }))
  useEffect(() => {
    writeStoredState(ANALYTICS_STATE_KEY, { filters, page, pageSize })
  }, [filters, page, pageSize])

  async function runAnalytics() {
    setLoading(true)
    setError('')
    try {
      const payload = {
        ...filters,
        min_reposts: String(Math.max(1, Number(filters.min_reposts) || 1)),
      }
      const res = await api.reposts(payload)
      setRows(res.items || [])
    } catch (e) {
      setRows([])
      setError(String(e?.message || e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    runAnalytics()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function openCompanyJobs(companyName) {
    const company = String(companyName || '').trim()
    if (!company || typeof onOpenJobs !== 'function') return
    onOpenJobs({ company, offset: '0' })
  }

  return (
    <div className="grid single">
      <div className="card">
        <div className="jobs-head">
          <h3>{t.analytics}</h3>
          <div className="pager">
            <span>{t.showing} {pg.start}-{pg.end} {t.of} {pg.total} {t.records}</span>
            <span>{t.pageSize}</span>
            <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value) || 50); setPage(1) }}>
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>{size}</option>
              ))}
            </select>
            <button disabled={pg.page <= 1} onClick={() => setPage(pg.page - 1)}>{t.prev}</button>
            <span>{t.page} {pg.page}/{pg.totalPages}</span>
            <button disabled={pg.page >= pg.totalPages} onClick={() => setPage(pg.page + 1)}>{t.next}</button>
            <button onClick={runAnalytics}>{t.run}</button>
            {loading && <span className="muted">{t.loading}</span>}
            {!loading && <span className="muted">rows={rows.length}</span>}
          </div>
        </div>
        {error && <div className="error-text">{error}</div>}
        <table>
          <thead>
            <tr><SortTh label={t.company} col="company" sort={sort} onSort={onSort} /><SortTh label={t.location} col="location" sort={sort} onSort={onSort} /><SortTh label={t.reposts} col="repost_count" sort={sort} onSort={onSort} /><SortTh label={t.durationDays} col="duration_days" sort={sort} onSort={onSort} /><SortTh label={t.first} col="first_repost_date" sort={sort} onSort={onSort} /><SortTh label={t.last} col="last_repost_date" sort={sort} onSort={onSort} /><SortTh label={t.distinctPosts} col="distinct_job_posts" sort={sort} onSort={onSort} /></tr>
            <tr className="filter-row">
              <th><input placeholder={t.company} value={filters.company} onChange={(e) => setFilters({ ...filters, company: e.target.value })} /></th>
              <th><CheckboxMultiSelect label={t.country} options={countryOptions} groups={countryGroups} selected={filters.countries} onChange={(v) => setFilters({ ...filters, countries: v })} t={t} applyMode /></th>
              <th><input placeholder={t.minReposts} value={filters.min_reposts} onChange={(e) => setFilters({ ...filters, min_reposts: e.target.value })} /></th>
              <th></th><th></th><th></th><th></th>
            </tr>
          </thead>
          <tbody>
            {pg.items.map((r, idx) => (
              <tr key={`${r.company}-${idx}`}>
                <td>
                  <button type="button" className="link-btn" onClick={() => openCompanyJobs(r.company)}>
                    {r.company}
                  </button>
                </td>
                <td>{r.location}</td><td>{r.repost_count}</td><td>{r.duration_days}</td><td>{r.first_repost_date}</td><td>{r.last_repost_date}</td><td>{r.distinct_job_posts}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function AutomationTab({ t, lang, onDataChanged }) {
  const automationView = useMemo(() => readStoredState(AUTOMATION_STATE_KEY, {}), [])
  const [schedules, setSchedules] = useState([])
  const [mergedSchedules, setMergedSchedules] = useState([])
  const [runs, setRuns] = useState([])
  const [scheduleSort, setScheduleSort] = useState({ key: 'id', dir: 'desc' })
  const [runSort, setRunSort] = useState({ key: 'id', dir: 'desc' })
  const [schedulePage, setSchedulePage] = useState(() => Number(automationView?.schedulePage) || 1)
  const [runPage, setRunPage] = useState(() => Number(automationView?.runPage) || 1)
  const [schedulePageSize, setSchedulePageSize] = useState(() => Number(automationView?.schedulePageSize) || 50)
  const [runPageSize, setRunPageSize] = useState(() => Number(automationView?.runPageSize) || 50)
  const [manualActionPending, setManualActionPending] = useState(false)
  const [editingScheduleId, setEditingScheduleId] = useState(null)
  const [form, setForm] = useState({
    name: 'New Schedule',
    pipeline_type: 'filtered_jobs',
    frequency: 'every_hours',
    every_hours: 6,
    run_time: '09:00',
    weekdays: [1, 3, 5],
    window_days: 30,
    max_jobs: 200,
    auto_eval_fit: true,
    auto_generate_cv: false,
    run_now_on_create: true,
    fit_threshold: 75,
    shutdown_when_completed: false,
  })

  async function reload() {
    const [schedulesRes, runsRes] = await Promise.allSettled([
      api.schedules(),
      api.runs(50),
    ])
    const autoSchedules = schedulesRes.status === 'fulfilled' ? (schedulesRes.value.items || []) : []
    const runItems = runsRes.status === 'fulfilled' ? (runsRes.value.items || []) : []
    setSchedules(autoSchedules)
    setRuns(runItems)
    setMergedSchedules(
      autoSchedules.map((item) => ({
        ...item,
        source: 'automation_schedules',
      })),
    )
  }

  async function reloadAndNotify() {
    await reload()
    if (typeof onDataChanged === 'function') {
      await onDataChanged()
    }
  }

  function isRunningStatus(value) {
    return ['running', 'dang chay', 'đang chạy'].includes(String(value || '').toLowerCase())
  }

  function runDetailPreview(run) {
    const detail = run?.detail_json || {}
    return (
      detail.progress_message ||
      detail.phase ||
      (Array.isArray(detail.stdout_tail_lines) ? detail.stdout_tail_lines[detail.stdout_tail_lines.length - 1] : '') ||
      ''
    )
  }

  function isPendingScheduledRun(run) {
    return String(run?.status || '').toLowerCase() === 'pending' && Boolean(String(run?.scheduled_for || run?.detail_json?.scheduled_for || '').trim())
  }

  function openRunLog(run) {
    const detail = run?.detail_json || {}
    const logPath = String(detail.log_path || '').trim()
    if (!logPath) return
    openLogViewer(logPath, {
      runId: run?.id,
      actionType: run?.action_type,
      running: isRunningStatus(run?.status),
    })
  }

  async function startManualAction(action_type, args = []) {
    setManualActionPending(true)
    try {
      await api.triggerAction({ action_type, args })
      await reloadAndNotify()
    } finally {
      setManualActionPending(false)
    }
  }

  async function startLearningEtlSchedule() {
    setManualActionPending(true)
    try {
      await api.createSchedule({
        name: 'Daily Learning ETL',
        cron_expr: '15 2 * * *',
        timezone: 'Asia/Ho_Chi_Minh',
        enabled: true,
        pipeline_type: 'learning_etl',
        crawl_config: {
          topic_keys: [],
          daily_target_per_topic: 20,
          seed_path: 'learning_plan.md',
          enqueue_now: true,
          max_attempts: 3,
          crawl_enabled: true,
          crawl_per_topic_limit: 10,
          crawl_sources: [],
        },
        auto_eval_fit: true,
        auto_generate_cv: false,
        fit_threshold: 75,
      })
      await reloadAndNotify()
    } finally {
      setManualActionPending(false)
    }
  }

  useEffect(() => { reload() }, [])
  useEffect(() => {
    if (!runs.some((r) => isRunningStatus(r.status))) return undefined
    const timer = window.setInterval(() => {
      reload().catch(() => {})
    }, 3000)
    return () => window.clearInterval(timer)
  }, [runs])

  const summary = useMemo(() => {
    const success = runs.filter((r) => ['success', 'thanh cong', 'thÃ nh cÃ´ng'].includes(String(r.status || '').toLowerCase())).length
    const failed = runs.filter((r) => ['failed', 'that bai', 'tháº¥t báº¡i'].includes(String(r.status || '').toLowerCase())).length
    return {
      total: runs.length,
      success,
      failed,
      lastRunAt: runs[0]?.started_at || '',
    }
  }, [runs])
  const activeCrawlRuns = useMemo(
    () => runs.filter((r) => isRunningStatus(r.status) && ['crawl_filtered', 'crawl_applied'].includes(String(r.action_type || '').toLowerCase())),
    [runs],
  )
  const latestCrawlRun = useMemo(
    () => runs.find((r) => ['crawl_filtered', 'crawl_applied'].includes(String(r.action_type || '').toLowerCase())) || null,
    [runs],
  )
  const latestCrawlLogPath = useMemo(
    () => String(latestCrawlRun?.detail_json?.log_path || '').trim(),
    [latestCrawlRun],
  )
  const scheduleRows = useMemo(() => sortRows(mergedSchedules, scheduleSort), [mergedSchedules, scheduleSort])
  const runRows = useMemo(() => sortRows(runs, runSort), [runs, runSort])
  const schedulePg = useMemo(() => paginateRows(scheduleRows, schedulePage, schedulePageSize), [scheduleRows, schedulePage, schedulePageSize])
  const runPg = useMemo(() => paginateRows(runRows, runPage, runPageSize), [runRows, runPage, runPageSize])
  const onScheduleSort = (key) => setScheduleSort((prev) => ({ key, dir: prev.key === key && prev.dir === 'asc' ? 'desc' : 'asc' }))
  const onRunSort = (key) => setRunSort((prev) => ({ key, dir: prev.key === key && prev.dir === 'asc' ? 'desc' : 'asc' }))

  const cronExpr = useMemo(() => buildCronExpr(form), [form])
  useEffect(() => {
    writeStoredState(AUTOMATION_STATE_KEY, {
      schedulePage,
      runPage,
      schedulePageSize,
      runPageSize,
    })
  }, [schedulePage, runPage, schedulePageSize, runPageSize])

  function scheduleToForm(schedule) {
    const crawlConfig = schedule?.crawl_config_json || {}
    const baseForm = {
      name: String(schedule?.name || 'New Schedule'),
      pipeline_type: String(schedule?.pipeline_type || 'filtered_jobs'),
      frequency: 'every_hours',
      every_hours: 6,
      run_time: '09:00',
      weekdays: [1, 3, 5],
      window_days: Number(crawlConfig.window_days) || 30,
      max_jobs: Number(crawlConfig.max_jobs) || 200,
      auto_eval_fit: Boolean(schedule?.auto_eval_fit ?? true),
      auto_generate_cv: Boolean(schedule?.auto_generate_cv ?? false),
      run_now_on_create: true,
      fit_threshold: Number(schedule?.fit_threshold) || 75,
      shutdown_when_completed: Boolean(crawlConfig.shutdown_when_completed ?? false),
    }
    return parseScheduleFormFromCron(schedule?.cron_expr, baseForm)
  }

  function buildSchedulePayloadFromForm(overrides = {}, schedule = null) {
    const sourceForm = form
    const crawlConfig = schedule?.crawl_config_json || {}
    const payload = {
      name: String(overrides.name ?? sourceForm.name ?? 'New Schedule').trim() || 'New Schedule',
      enabled: typeof overrides.enabled === 'boolean' ? overrides.enabled : Boolean(schedule?.enabled ?? true),
      cron_expr: overrides.cron_expr || cronExpr,
      timezone: overrides.timezone || schedule?.timezone || TIMEZONE,
      pipeline_type: overrides.pipeline_type || sourceForm.pipeline_type,
      auto_eval_fit: Boolean(overrides.auto_eval_fit ?? sourceForm.auto_eval_fit),
      fit_cv_profile: String(overrides.fit_cv_profile || schedule?.fit_cv_profile || 'full_doc_stlye'),
      auto_generate_cv: Boolean(overrides.auto_generate_cv ?? sourceForm.auto_generate_cv),
      fit_threshold: Number(overrides.fit_threshold ?? sourceForm.fit_threshold) || 75,
      crawl_config: {
        ...crawlConfig,
      },
    }
    if (payload.pipeline_type === 'learning_etl') {
      payload.crawl_config = {
        ...payload.crawl_config,
        topic_keys: Array.isArray(crawlConfig.topic_keys) ? crawlConfig.topic_keys : [],
        daily_target_per_topic: Number(crawlConfig.daily_target_per_topic) || 20,
        seed_path: String(crawlConfig.seed_path || 'learning_plan.md'),
        enqueue_now: Boolean(sourceForm.run_now_on_create),
        max_attempts: Number(crawlConfig.max_attempts) || 3,
        crawl_enabled: true,
        crawl_per_topic_limit: Number(crawlConfig.crawl_per_topic_limit) || 10,
        crawl_sources: Array.isArray(crawlConfig.crawl_sources) ? crawlConfig.crawl_sources : [],
        shutdown_when_completed: Boolean(overrides.shutdown_when_completed ?? sourceForm.shutdown_when_completed),
      }
    } else {
      payload.crawl_config = {
        ...payload.crawl_config,
        window_days: Number(overrides.window_days ?? sourceForm.window_days) || 30,
        max_jobs: Number(overrides.max_jobs ?? sourceForm.max_jobs) || 200,
        shutdown_when_completed: Boolean(overrides.shutdown_when_completed ?? sourceForm.shutdown_when_completed),
      }
    }
    return payload
  }

  function buildSchedulePayloadFromSchedule(schedule, overrides = {}) {
    const sourceForm = scheduleToForm(schedule)
    const crawlConfig = schedule?.crawl_config_json || {}
    const payload = {
      name: String(overrides.name ?? schedule?.name ?? 'New Schedule').trim() || 'New Schedule',
      enabled: typeof overrides.enabled === 'boolean' ? overrides.enabled : Boolean(schedule?.enabled ?? true),
      cron_expr: overrides.cron_expr || schedule?.cron_expr || buildCronExpr(sourceForm),
      timezone: overrides.timezone || schedule?.timezone || TIMEZONE,
      pipeline_type: overrides.pipeline_type || String(schedule?.pipeline_type || sourceForm.pipeline_type),
      auto_eval_fit: Boolean(overrides.auto_eval_fit ?? schedule?.auto_eval_fit ?? true),
      fit_cv_profile: String(overrides.fit_cv_profile || schedule?.fit_cv_profile || 'full_doc_stlye'),
      auto_generate_cv: Boolean(overrides.auto_generate_cv ?? schedule?.auto_generate_cv ?? false),
      fit_threshold: Number(overrides.fit_threshold ?? schedule?.fit_threshold) || 75,
      crawl_config: {
        ...crawlConfig,
      },
    }
    if (payload.pipeline_type === 'learning_etl') {
      payload.crawl_config = {
        ...payload.crawl_config,
        topic_keys: Array.isArray(crawlConfig.topic_keys) ? crawlConfig.topic_keys : [],
        daily_target_per_topic: Number(crawlConfig.daily_target_per_topic) || 20,
        seed_path: String(crawlConfig.seed_path || 'learning_plan.md'),
        enqueue_now: Boolean(sourceForm.run_now_on_create),
        max_attempts: Number(crawlConfig.max_attempts) || 3,
        crawl_enabled: true,
        crawl_per_topic_limit: Number(crawlConfig.crawl_per_topic_limit) || 10,
        crawl_sources: Array.isArray(crawlConfig.crawl_sources) ? crawlConfig.crawl_sources : [],
        shutdown_when_completed: Boolean(overrides.shutdown_when_completed ?? sourceForm.shutdown_when_completed),
      }
    } else {
      payload.crawl_config = {
        ...payload.crawl_config,
        window_days: Number(overrides.window_days ?? sourceForm.window_days) || 30,
        max_jobs: Number(overrides.max_jobs ?? sourceForm.max_jobs) || 200,
        shutdown_when_completed: Boolean(overrides.shutdown_when_completed ?? sourceForm.shutdown_when_completed),
      }
    }
    return payload
  }

  function toggleWeekday(dayValue) {
    const current = new Set(form.weekdays)
    if (current.has(dayValue)) current.delete(dayValue)
    else current.add(dayValue)
    setForm({ ...form, weekdays: Array.from(current).sort((a, b) => a - b) })
  }

  function startEditSchedule(schedule) {
    setEditingScheduleId(schedule?.id || null)
    setForm(scheduleToForm(schedule))
  }

  function cancelEditSchedule() {
    setEditingScheduleId(null)
    setForm({
      name: 'New Schedule',
      pipeline_type: 'filtered_jobs',
      frequency: 'every_hours',
      every_hours: 6,
      run_time: '09:00',
      weekdays: [1, 3, 5],
      window_days: 30,
      max_jobs: 200,
      auto_eval_fit: true,
      auto_generate_cv: false,
      run_now_on_create: true,
      fit_threshold: 75,
      shutdown_when_completed: false,
    })
  }

  async function saveSchedule() {
    const payload = buildSchedulePayloadFromForm()
    if (editingScheduleId) {
      await api.updateSchedule(editingScheduleId, payload)
      await reloadAndNotify()
      cancelEditSchedule()
      return
    }
    const created = await api.createSchedule({
      ...payload,
      enabled: true,
    })
    if (form.run_now_on_create && created?.id) {
      await api.runScheduleNow(created.id)
    }
    await reloadAndNotify()
  }

  async function toggleScheduleEnabled(schedule) {
    const nextEnabled = !Boolean(schedule?.enabled)
    await api.updateSchedule(schedule.id, buildSchedulePayloadFromSchedule(schedule, { enabled: nextEnabled }))
    await reloadAndNotify()
  }

  async function deleteSchedule(schedule) {
    if (!window.confirm(t.confirmDeleteSchedule)) return
    await api.deleteSchedule(schedule.id)
    if (editingScheduleId === schedule.id) {
      cancelEditSchedule()
    }
    await reloadAndNotify()
  }

  async function pauseRun(run) {
    await api.pauseRun(run.id)
    await reloadAndNotify()
  }

  async function deleteRun(run) {
    if (!window.confirm(`${t.delete || 'Delete'} run #${run.id}?`)) return
    await api.deleteRun(run.id)
    await reloadAndNotify()
  }

  async function recallRun(run) {
    if (!window.confirm(`Recall pending run #${run.id} now?`)) return
    await api.recallRun(run.id)
    await reloadAndNotify()
  }

  async function rescheduleRun(run) {
    const currentValue = toDateTimeLocalValue(run?.scheduled_for || run?.detail_json?.scheduled_for || '')
    const nextValue = window.prompt('Set a new time for this pending run (YYYY-MM-DDTHH:mm)', currentValue)
    if (!nextValue) return
    const runAt = toIsoFromDateTimeLocal(nextValue)
    if (!runAt) {
      window.alert('Invalid date/time format.')
      return
    }
    await api.rescheduleRun(run.id, { run_at: runAt })
    await reloadAndNotify()
  }

  return (
    <div className="grid single">
      <div className="grid">
        <Card title={t.automationSummary} value={summary.total} />
        <Card title={t.successRuns} value={summary.success} />
        <Card title={t.failedRuns} value={summary.failed} />
        <Card title={t.lastRunGmt7} value={formatGmt7(summary.lastRunAt, lang)} />
      </div>

      <div className="card">
        <h3>{t.manualActions}</h3>
        <div className="filters">
          <button disabled={manualActionPending} onClick={async () => { await startManualAction('crawl_filtered', ['--window-days', '30']) }}>{t.runCrawlFiltered}</button>
          <button disabled={manualActionPending} onClick={async () => { await startManualAction('crawl_applied') }}>{t.runCrawlApplied}</button>
          <button disabled={manualActionPending} onClick={async () => { await startManualAction('generate_cv') }}>{t.runGenerateCv}</button>
          <button disabled={manualActionPending} onClick={async () => { await startLearningEtlSchedule() }}>{t.scheduleLearningEtl}</button>
        </div>
        </div>

      <div className="card">
        <h3>Run Crawl Monitor</h3>
        {activeCrawlRuns.length > 0 ? (
          <div className="grid">
            {activeCrawlRuns.map((run) => {
              const detail = run?.detail_json || {}
              const logPath = String(detail.log_path || '').trim()
              const lineCount = Number(detail.line_count || 0)
              const phase = String(detail.phase || 'starting')
              const progress = runDetailPreview(run) || '-'
              return (
                <div key={run.id} className="card" style={{ margin: 0 }}>
                  <div><b>Run #{run.id}</b> | {run.action_type}</div>
                  <div><b>Status:</b> {normalizeStatus(run.status, lang)}</div>
                  <div><b>Phase:</b> <code>{phase}</code></div>
                  <div><b>Updated:</b> {progress}</div>
                  <div><b>Log lines:</b> {lineCount}</div>
                  <div><b>Started:</b> {formatGmt7(run.started_at, lang)}</div>
                  <div>
                    <b>Log:</b>{' '}
                    {logPath ? (
                      <button className="link-btn" onClick={() => openRunLog(run)}>
                        {logPath.split(/[\\/]/).pop()}
                      </button>
                    ) : '-'}
                  </div>
                </div>
              )
            })}
          </div>
        ) : latestCrawlRun ? (
          <div>
            <div><b>Last crawl:</b> #{latestCrawlRun.id} | {latestCrawlRun.action_type} | {normalizeStatus(latestCrawlRun.status, lang)}</div>
            <div><b>Latest step:</b> {runDetailPreview(latestCrawlRun) || '-'}</div>
            <div><b>Started:</b> {formatGmt7(latestCrawlRun.started_at, lang)}</div>
            <div>
              <b>Log:</b>{' '}
              {latestCrawlLogPath ? (
                <button className="link-btn" onClick={() => openRunLog(latestCrawlRun)}>
                  {latestCrawlLogPath.split(/[\\/]/).pop()}
                </button>
              ) : '-'}
            </div>
          </div>
        ) : (
          <div className="muted">No crawl run yet.</div>
        )}
      </div>

      <div className="card">
        <h3>{editingScheduleId ? `${t.editSchedule || 'Edit schedule'} #${editingScheduleId}` : t.createSchedule}</h3>
        <div className="schedule-grid">
          <label>{t.scheduleName}<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          <label>{t.scheduleType}
            <select value={form.pipeline_type} onChange={(e) => setForm({ ...form, pipeline_type: e.target.value })}>
              <option value="filtered_jobs">{t.filteredJobs}</option>
              <option value="applied_jobs">{t.appliedJobsPipeline}</option>
              <option value="learning_etl">{t.learningEtlPipeline || 'Learning ETL'}</option>
            </select>
          </label>
          <label>{t.frequency}
            <select value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value })}>
              <option value="every_hours">{t.everyHours}</option>
              <option value="daily">{t.daily}</option>
              <option value="weekly">{t.weekly}</option>
            </select>
          </label>

          {form.frequency === 'every_hours' && (
            <label>{t.everyHours}<input type="number" min="1" max="24" value={form.every_hours} onChange={(e) => setForm({ ...form, every_hours: e.target.value })} /></label>
          )}
          {form.frequency !== 'every_hours' && (
            <label>{t.runAt}<input type="time" value={form.run_time} onChange={(e) => setForm({ ...form, run_time: e.target.value })} /></label>
          )}

          {form.frequency === 'weekly' && (
            <div className="weekday-wrap">
              <div className="muted">{t.weekdays}</div>
              <div className="weekdays">
                {weekdayOptions.map((d) => (
                  <label key={d.value} className="wk-item">
                    <input type="checkbox" checked={form.weekdays.includes(d.value)} onChange={() => toggleWeekday(d.value)} />
                    <span>{t[d.key]}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          <label>{t.windowDays}<input type="number" min="1" max="120" value={form.window_days} onChange={(e) => setForm({ ...form, window_days: e.target.value })} /></label>
          <label>{t.maxJobs}<input type="number" min="1" max="2000" value={form.max_jobs} onChange={(e) => setForm({ ...form, max_jobs: e.target.value })} /></label>
          <label>{t.threshold}<input type="number" min="0" max="100" value={form.fit_threshold} onChange={(e) => setForm({ ...form, fit_threshold: e.target.value })} /></label>

          <label className="toggle-row"><input type="checkbox" checked={form.auto_eval_fit} onChange={(e) => setForm({ ...form, auto_eval_fit: e.target.checked })} />{t.autoEvaluateFit}</label>
          <label className="toggle-row"><input type="checkbox" checked={form.auto_generate_cv} onChange={(e) => setForm({ ...form, auto_generate_cv: e.target.checked })} />{t.autoGenerateCv}</label>
          <label className="toggle-row"><input type="checkbox" checked={form.shutdown_when_completed} onChange={(e) => setForm({ ...form, shutdown_when_completed: e.target.checked })} />{t.shutdownWhenCompleted}</label>
          {!editingScheduleId ? <label className="toggle-row"><input type="checkbox" checked={form.run_now_on_create} onChange={(e) => setForm({ ...form, run_now_on_create: e.target.checked })} />{t.runNowOnCreate || 'Run crawl right after create'}</label> : null}
        </div>

        <div className="cron-preview"><b>{t.cronPreview}:</b> <code>{cronExpr}</code></div>
        <div className="filters">
          <button onClick={saveSchedule}>{editingScheduleId ? (t.saveChanges || 'Save Changes') : t.create}</button>
          {editingScheduleId ? <button onClick={cancelEditSchedule}>{t.cancelEditSchedule || 'Cancel Edit'}</button> : null}
        </div>
      </div>

      <div className="card">
        <h3>{t.schedules || 'Schedules'}</h3>
        <div className="pager">
          <span>{t.showing} {schedulePg.start}-{schedulePg.end} {t.of} {schedulePg.total} {t.records}</span>
          <span>{t.pageSize}</span>
          <select value={schedulePageSize} onChange={(e) => { setSchedulePageSize(Number(e.target.value) || 50); setSchedulePage(1) }}>
            {PAGE_SIZE_OPTIONS.map((size) => (
              <option key={size} value={size}>{size}</option>
            ))}
          </select>
          <button disabled={schedulePg.page <= 1} onClick={() => setSchedulePage(schedulePg.page - 1)}>{t.prev}</button>
          <span>{t.page} {schedulePg.page}/{schedulePg.totalPages}</span>
          <button disabled={schedulePg.page >= schedulePg.totalPages} onClick={() => setSchedulePage(schedulePg.page + 1)}>{t.next}</button>
        </div>
        <table>
          <thead><tr><SortTh label="ID" col="id" sort={scheduleSort} onSort={onScheduleSort} /><SortTh label={t.pipeline} col="pipeline_type" sort={scheduleSort} onSort={onScheduleSort} /><SortTh label="Name" col="name" sort={scheduleSort} onSort={onScheduleSort} /><SortTh label={t.enabled} col="enabled" sort={scheduleSort} onSort={onScheduleSort} /><SortTh label={t.shutdownWhenCompleted} col="shutdown_when_completed" sort={scheduleSort} onSort={onScheduleSort} /><SortTh label={t.cron} col="cron_expr" sort={scheduleSort} onSort={onScheduleSort} /><SortTh label={t.nextRun} col="next_run_at" sort={scheduleSort} onSort={onScheduleSort} /><SortTh label={t.threshold} col="fit_threshold" sort={scheduleSort} onSort={onScheduleSort} /><th>{t.actions}</th></tr></thead>
          <tbody>
            {schedulePg.items.map((s) => (
              <tr key={`${s.source}_${s.id}`}>
                <td>{s.id}</td>
                <td>{s.pipeline_type}</td>
                <td>
                  <div>{s.name}</div>
                  {hasShutdownFlag(s) ? <div className="inline-badge inline-badge-warn">{shutdownBadgeText(s)}</div> : null}
                </td>
                <td>{s.enabled ? t.yes : t.no}</td>
                <td>{hasShutdownFlag(s) ? t.yes : t.no}</td>
                <td>{s.cron_expr}</td>
                <td>{formatGmt7(s.next_run_at || '', lang)}</td>
                <td>{s.fit_threshold || '-'}</td>
                <td className="row-actions schedule-action-row">
                  <button onClick={() => toggleScheduleEnabled(s)}>{s.enabled ? (t.pauseSchedule || 'Pause schedule') : (t.resumeSchedule || 'Resume schedule')}</button>
                  <button onClick={() => startEditSchedule(s)}>{t.editSchedule || 'Edit schedule'}</button>
                  <button onClick={() => deleteSchedule(s)}>{t.delete}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Runs</h3>
        <div className="pager">
          <span>{t.showing} {runPg.start}-{runPg.end} {t.of} {runPg.total} {t.records}</span>
          <span>{t.pageSize}</span>
          <select value={runPageSize} onChange={(e) => { setRunPageSize(Number(e.target.value) || 50); setRunPage(1) }}>
            {PAGE_SIZE_OPTIONS.map((size) => (
              <option key={size} value={size}>{size}</option>
            ))}
          </select>
          <button disabled={runPg.page <= 1} onClick={() => setRunPage(runPg.page - 1)}>{t.prev}</button>
          <span>{t.page} {runPg.page}/{runPg.totalPages}</span>
          <button disabled={runPg.page >= runPg.totalPages} onClick={() => setRunPage(runPg.page + 1)}>{t.next}</button>
        </div>
        <table>
          <thead><tr><SortTh label="ID" col="id" sort={runSort} onSort={onRunSort} /><SortTh label="Action" col="action_type" sort={runSort} onSort={onRunSort} /><SortTh label={t.status} col="status" sort={runSort} onSort={onRunSort} /><SortTh label="By" col="triggered_by" sort={runSort} onSort={onRunSort} /><SortTh label={t.startedGmt7} col="started_at" sort={runSort} onSort={onRunSort} /><th>Progress</th><th>{t.actions}</th></tr></thead>
          <tbody>
            {runPg.items.map((r) => (
              <tr key={r.id}>
                <td>{r.id}</td>
                <td>
                  <div>{r.action_type}</div>
                  {hasShutdownFlag(r) ? <div className="inline-badge inline-badge-warn">{shutdownBadgeText(r)}</div> : null}
                </td>
                <td>{normalizeStatus(r.status, lang)}</td>
                <td>{r.triggered_by}</td>
                <td>{formatGmt7(r.started_at, lang)}</td>
                <td title={String(runDetailPreview(r) || '')}>
                  <div>{runDetailPreview(r) || '-'}</div>
                  {isPendingScheduledRun(r) ? <div className="muted">scheduled_for={formatGmt7(r.scheduled_for || r?.detail_json?.scheduled_for || '', lang)}</div> : null}
                  {String(r?.detail_json?.log_path || '').trim() ? (
                    <button className="link-btn" onClick={() => openRunLog(r)}>
                      {String(r.detail_json.log_path || '').trim().split(/[\\/]/).pop()}
                    </button>
                  ) : null}
                </td>
                <td className="row-actions schedule-action-row">
                  <button
                    onClick={() => pauseRun(r)}
                    disabled={!String(r.status || '').toLowerCase().includes('running')}
                  >
                    {t.pauseRun || 'Pause'}
                  </button>
                  <button
                    onClick={() => recallRun(r)}
                    disabled={!isPendingScheduledRun(r)}
                  >
                    Recall
                  </button>
                  <button
                    onClick={() => rescheduleRun(r)}
                    disabled={!isPendingScheduledRun(r)}
                  >
                    Set Time
                  </button>
                  <button
                    onClick={() => deleteRun(r)}
                    disabled={['running', 'pending'].includes(String(r.status || '').toLowerCase())}
                  >
                    {t.delete}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function InterviewQaPredictionTab({ t }) {
  const [manualActionPending, setManualActionPending] = useState(false)
  const [predictionActionMessage, setPredictionActionMessage] = useState('')
  const [predictionActionError, setPredictionActionError] = useState('')
  const [predictionForm, setPredictionForm] = useState({
    jobIds: '',
    cvPath: 'input/full_doc_stlye.txt',
    recentDays: '14',
    limit: '5',
    startAt: '',
    jdText: '',
    jdFileName: '',
    force: false,
    shutdownWhenCompleted: false,
  })
  const [predictionFileError, setPredictionFileError] = useState('')

  function handlePredictionFile(event) {
    const file = event?.target?.files?.[0]
    if (!file) {
      setPredictionForm((prev) => ({ ...prev, jdFileName: '' }))
      setPredictionFileError('')
      return
    }
    setPredictionFileError('')
    readFileTextInput(file)
      .then((text) => {
        setPredictionForm((prev) => ({ ...prev, jdText: String(text || ''), jdFileName: file.name }))
      })
      .catch(() => {
        setPredictionFileError('Failed to read file')
      })
  }

  async function runPredictionManualAction() {
    const args = ['--mode', 'nightly']
    const parsedJobIds = String(predictionForm.jobIds || '')
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean)
      .map((value) => Number(value))
      .filter((value) => Number.isFinite(value) && value > 0)
    parsedJobIds.forEach((jobId) => {
      args.push('--job-id', String(jobId))
    })
    const cvPath = String(predictionForm.cvPath || '').trim()
    if (cvPath) {
      args.push('--cv-path', cvPath)
    }
    const recentDays = Math.max(0, Number(predictionForm.recentDays) || 0)
    args.push('--recent-days', String(recentDays))
    const limit = Math.max(1, Number(predictionForm.limit) || 1)
    args.push('--limit', String(limit))
    if (predictionForm.force) {
      args.push('--force')
    }
    if (predictionForm.shutdownWhenCompleted) {
      args.push('--shutdown-when-completed')
    }
    const jdText = String(predictionForm.jdText || '').trim()
    if (jdText) {
      const encoded = encodeBase64Text(jdText)
      if (encoded) {
        args.push('--jd-text-base64', encoded)
      }
    }
    const runAt = toIsoFromDateTimeLocal(predictionForm.startAt)
    if (runAt) {
      learningQuizLogger.info('Interview QA submit scheduled', {
        source: 'learning_quiz',
        run_at: runAt,
        job_ids_count: parsedJobIds.length,
        cv_path: cvPath || '',
        recent_days: recentDays,
        limit,
        has_jd_text: Boolean(jdText),
        has_file: Boolean(predictionForm.jdFileName),
      })
    } else {
      learningQuizLogger.info('Interview QA submit immediate', {
        source: 'learning_quiz',
        job_ids_count: parsedJobIds.length,
        cv_path: cvPath || '',
        recent_days: recentDays,
        limit,
        has_jd_text: Boolean(jdText),
        has_file: Boolean(predictionForm.jdFileName),
      })
    }
    setPredictionActionMessage('')
    setPredictionActionError('')
    setManualActionPending(true)
    try {
      await api.triggerAction({
        action_type: 'predict_interview_qa',
        args,
        run_at: runAt,
        triggered_by: 'learning_quiz',
      })
      setPredictionActionMessage(runAt ? `Scheduled predict_interview_qa for ${runAt}` : 'Triggered predict_interview_qa')
    } catch (error) {
      setPredictionActionError(String(error?.message || error))
    } finally {
      setManualActionPending(false)
    }
  }

  return (
    <div className="card">
      <div className="prediction-panel-header">
        <h3>{t.interviewQaTab || 'Interview Q&A'}</h3>
        {t.predictJdHint ? <p className="muted">{t.predictJdHint}</p> : null}
      </div>
      <div className="prediction-grid">
        <label className="action-input-label">
          <span>{t.predictJobIds || 'Job IDs'}</span>
          <input
            placeholder={t.predictJobIdsPlaceholder || 'e.g. 4381111111,4382222222'}
            value={predictionForm.jobIds}
            onChange={(event) => setPredictionForm((prev) => ({ ...prev, jobIds: event.target.value }))}
          />
        </label>
        <label className="action-input-label">
          <span>{t.predictCvPath || 'CV path'}</span>
          <input
            placeholder="input/full_doc_stlye.txt"
            value={predictionForm.cvPath}
            onChange={(event) => setPredictionForm((prev) => ({ ...prev, cvPath: event.target.value }))}
          />
        </label>
        <label className="action-input-label">
          <span>{t.predictRecentDays || 'Recent days'}</span>
          <input
            type="number"
            min="0"
            value={predictionForm.recentDays}
            onChange={(event) => setPredictionForm((prev) => ({ ...prev, recentDays: event.target.value }))}
          />
        </label>
        <label className="action-input-label">
          <span>{t.predictMaxJobs || 'Max jobs'}</span>
          <input
            type="number"
            min="1"
            value={predictionForm.limit}
            onChange={(event) => setPredictionForm((prev) => ({ ...prev, limit: event.target.value }))}
          />
        </label>
        <label className="action-input-label">
          <span>{t.predictStartAt || 'Start job time'}</span>
          <input
            type="datetime-local"
            value={predictionForm.startAt}
            onChange={(event) => setPredictionForm((prev) => ({ ...prev, startAt: event.target.value }))}
          />
        </label>
      </div>
      <label className="action-input-label">
        <span>{t.predictJdText || 'JD text'}</span>
        <textarea
          rows="3"
          value={predictionForm.jdText}
          onChange={(event) => setPredictionForm((prev) => ({ ...prev, jdText: event.target.value }))}
          placeholder="Paste JD text to encode it for prediction"
        />
      </label>
      <label className="action-input-label">
        <span>{t.predictJdFile || 'JD file'}</span>
        <input
          type="file"
          accept=".txt,.md,.json,.docx,.doc"
          onChange={handlePredictionFile}
        />
        {predictionForm.jdFileName ? <div className="muted">Loaded: {predictionForm.jdFileName}</div> : null}
        {predictionFileError ? <div className="error-text">{predictionFileError}</div> : null}
      </label>
      <div className="filters">
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={predictionForm.force}
            onChange={(event) => setPredictionForm((prev) => ({ ...prev, force: event.target.checked }))}
          />
          <span>{t.predictForce || 'Force run even when feature flag is off'}</span>
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={predictionForm.shutdownWhenCompleted}
            onChange={(event) => setPredictionForm((prev) => ({ ...prev, shutdownWhenCompleted: event.target.checked }))}
          />
          <span>{t.shutdownWhenCompleted || 'Shut down when completed'}</span>
        </label>
        <button disabled={manualActionPending} onClick={runPredictionManualAction}>
          {t.runGenerateInterviewQa || 'Generate Interview Q&A'}
        </button>
      </div>
      {predictionActionMessage ? <div className="muted">{predictionActionMessage}</div> : null}
      {predictionActionError ? <div className="error-text">{predictionActionError}</div> : null}
    </div>
  )
}

function LearningQuizTab({ t, lang }) {
  const [topics, setTopics] = useState([])
  const [topicKey, setTopicKey] = useState('')
  const [quizLang, setQuizLang] = useState(lang || 'en')
  const [subTab, setSubTab] = useState('quiz')
  const [quiz, setQuiz] = useState([])
  const [answers, setAnswers] = useState({})
  const [currentIdx, setCurrentIdx] = useState(0)
  const [result, setResult] = useState(null)
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(false)
  const [knowledge, setKnowledge] = useState([])
  const [knowledgeMeta, setKnowledgeMeta] = useState({ topicKey: '', lang: '' })
  const [knowledgeLoading, setKnowledgeLoading] = useState(false)
  const [knowledgeError, setKnowledgeError] = useState('')

  async function reloadLearningData() {
    const [topicsRes, historyRes] = await Promise.all([
      api.learningTopics(),
      api.learningQuizHistory(10).catch(() => ({ items: [] })),
    ])
    const topicItems = topicsRes.items || []
    setTopics(topicItems)
    if (!topicKey && topicItems[0]?.topic_key) setTopicKey(topicItems[0].topic_key)
    setHistory(historyRes.items || [])
  }

  useEffect(() => {
    reloadLearningData().catch(() => {})
  }, [])

  async function startQuiz() {
    setSubTab('quiz')
    if (!topicKey) return
    setLoading(true)
    setResult(null)
    try {
      const res = await api.learningQuiz({ topic_key: topicKey, limit: 5, lang: quizLang })
      setQuiz(res.items || [])
      setAnswers({})
      setCurrentIdx(0)
    } finally {
      setLoading(false)
    }
  }

  async function loadKnowledge(force = false) {
    if (!topicKey) return
    if (!force && knowledgeMeta.topicKey === topicKey && knowledgeMeta.lang === quizLang && knowledge.length > 0) return
    setKnowledgeLoading(true)
    setKnowledgeError('')
    try {
      const res = await api.learningKnowledge({ topic_key: topicKey, limit: 50, lang: quizLang })
      setKnowledge(res.items || [])
      setKnowledgeMeta({ topicKey, lang: quizLang })
    } catch (e) {
      setKnowledge([])
      setKnowledgeError(String(e?.message || e))
    } finally {
      setKnowledgeLoading(false)
    }
  }

  async function submitQuiz() {
    if (!topicKey || quiz.length === 0) return
    setLoading(true)
    try {
      const payload = {
        topic_key: topicKey,
        lang: quizLang,
        items: quiz.map((item) => ({
          question_id: item.question_id,
          selected_answer_id: answers[item.question_id] || null,
        })),
      }
      const res = await api.submitLearningQuiz(payload)
      setResult(res)
      await reloadLearningData()
    } finally {
      setLoading(false)
    }
  }

  function goNext() {
    setCurrentIdx((idx) => Math.min(idx + 1, Math.max(0, quiz.length - 1)))
  }

  function goPrev() {
    setCurrentIdx((idx) => Math.max(idx - 1, 0))
  }

  useEffect(() => {
    if (subTab !== 'knowledge') return undefined
    loadKnowledge().catch(() => {})
    return undefined
  }, [subTab, topicKey, quizLang])

  const currentItem = quiz[currentIdx] || null
  const totalQuestions = quiz.length
  const localPickLang = (en, vi) => (quizLang === 'vi' && vi ? vi : en || vi || '')

  return (
    <div className="stack">
      <div className="card learning-toolbar">
        <div className="filter-grid">
          <label>
            <span>{t.topic}</span>
            <select value={topicKey} onChange={(e) => setTopicKey(e.target.value)}>
              {(topics || []).map((topic) => (
                <option key={topic.topic_key} value={topic.topic_key}>
                  {lang === 'vi' && topic.name_vi ? topic.name_vi : topic.name_en} ({topic.question_count})
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{t.quizLanguage}</span>
            <select value={quizLang} onChange={(e) => setQuizLang(e.target.value)}>
              <option value="en">English</option>
              <option value="vi">Tiếng Việt</option>
            </select>
          </label>
        </div>
        <div className="quiz-toolbar">
          <div className="subtabs">
            <button className={`subtab-btn ${subTab === 'quiz' ? 'active' : ''}`} onClick={() => setSubTab('quiz')}>
              {t.learningQuiz}
            </button>
            <button className={`subtab-btn ${subTab === 'knowledge' ? 'active' : ''}`} onClick={() => setSubTab('knowledge')}>
              {t.knowledgeTab || 'Knowledge'}
            </button>
            <button className={`subtab-btn ${subTab === 'interview_qa' ? 'active' : ''}`} onClick={() => setSubTab('interview_qa')}>
              {t.interviewQaTab || 'Interview Q&A'}
            </button>
          </div>
          <div className="row-actions-right">
            <button className="primary-btn" onClick={startQuiz} disabled={loading || !topicKey}>{t.startQuiz}</button>
            <button className="secondary-btn" onClick={submitQuiz} disabled={loading || quiz.length === 0}>{t.submitQuiz}</button>
          </div>
        </div>
      </div>

      {subTab === 'knowledge' ? (
        <div className="card">
          <div className="card-head">
            <div>
              <h3>{t.knowledgeTab || 'Knowledge'}</h3>
              <div className="muted">{t.knowledgeHint || ''}</div>
            </div>
          </div>
          {knowledgeLoading && <p className="muted">{t.loading}</p>}
          {knowledgeError && <div className="error-text">{knowledgeError}</div>}
          {!knowledgeLoading && !knowledgeError && (
            knowledge.length === 0 ? (
              <p className="muted">{t.noQuizQuestions}</p>
            ) : (
              <div className="knowledge-list">
                {knowledge.map((item, idx) => (
                  <div key={`knowledge_${item.question_id}`} className="knowledge-item">
                    <div className="quiz-question">
                      {idx + 1}. {localPickLang(item.question_en, item.question_vi) || item.question}
                    </div>
                    <div className="knowledge-answer"><strong>{t.correctAnswer}:</strong> {localPickLang(item.answer_en, item.answer_vi) || item.answer}</div>
                    <div className="knowledge-explanation"><strong>{t.explanation}:</strong> {localPickLang(item.explanation_en, item.explanation_vi) || item.explanation || '-'}</div>
                  </div>
                ))}
              </div>
            )
          )}
        </div>
      ) : subTab === 'interview_qa' ? (
        <InterviewQaPredictionTab t={t} />
      ) : (
        <div className="card">
          <h3>{t.learningQuiz}</h3>
          {quiz.length === 0 ? (
            <p className="muted">{t.noQuizQuestions}</p>
          ) : (
            <div className="quiz-list">
              <div className="quiz-meta">
                <span>{t.question || 'Question'} {currentIdx + 1}/{totalQuestions}</span>
                <div className="pager-inline">
                  <button onClick={goPrev} disabled={currentIdx === 0}>{t.prev || 'Prev'}</button>
                  <button onClick={goNext} disabled={currentIdx >= totalQuestions - 1}>{t.next || 'Next'}</button>
                </div>
              </div>
              {currentItem && (
                <div key={currentItem.question_id} className="quiz-item">
                  <div className="quiz-question">
                    {currentIdx + 1}. {localPickLang(currentItem.question_en, currentItem.question_vi) || currentItem.question}
                  </div>
                  <div className="quiz-choices">
                    {(currentItem.choices || []).map((choice) => (
                      <label key={`${currentItem.question_id}_${choice.answer_id}`} className="quiz-choice">
                        <input
                          type="radio"
                          name={`q_${currentItem.question_id}`}
                          checked={Number(answers[currentItem.question_id]) === Number(choice.answer_id)}
                          onChange={() => setAnswers((prev) => ({ ...prev, [currentItem.question_id]: choice.answer_id }))}
                        />
                        <span>{localPickLang(choice.text_en, choice.text_vi) || choice.text}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {result && (
        <div className="card">
          <h3>{t.score}: {result.score}/{result.total}</h3>
          <div className="quiz-results">
            {(result.results || []).map((item) => (
              <div key={`result_${item.question_id}`} className={`quiz-result ${item.is_correct ? 'ok' : 'bad'}`}>
                <div className="quiz-question">
                  {localPickLang(item.question, item.question) || localPickLang(item.question_en, item.question_vi)}
                </div>
                <div><strong>{t.correctAnswer}:</strong> {localPickLang(item.correct_answer_en, item.correct_answer_vi) || item.correct_answer}</div>
                <div><strong>{t.explanation}:</strong> {localPickLang(item.explanation_en, item.explanation_vi) || item.explanation || '-'}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <h3>{t.quizHistory}</h3>
        <table>
          <thead>
            <tr><th>ID</th><th>{t.topic}</th><th>{t.score}</th><th>{t.language}</th><th>{t.startedGmt7}</th></tr>
          </thead>
          <tbody>
            {(history || []).map((item) => (
              <tr key={item.id}>
                <td>{item.id}</td>
                <td>{lang === 'vi' && item.topic_name_vi ? item.topic_name_vi : item.topic_name_en}</td>
                <td>{item.score}/{item.total}</td>
                <td>{item.lang}</td>
                <td>{formatGmt7(item.created_at, lang)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function LogViewerPage() {
  const params = useMemo(() => {
    if (typeof window === 'undefined') return new URLSearchParams()
    return new URLSearchParams(window.location.search || '')
  }, [])
  const path = String(params.get('path') || '').trim()
  const runId = String(params.get('run_id') || '').trim()
  const actionType = String(params.get('action') || '').trim()
  const shouldPoll = String(params.get('running') || '').trim() === '1'
  const [content, setContent] = useState('')
  const [status, setStatus] = useState(path ? 'loading' : 'missing')
  const [error, setError] = useState('')
  const [lastLoadedAt, setLastLoadedAt] = useState('')

  useEffect(() => {
    if (typeof document !== 'undefined') {
      document.title = runId ? `Run #${runId} Log` : 'Run Log Viewer'
    }
  }, [runId])

  useEffect(() => {
    if (!path) return undefined
    let cancelled = false
    let timerId = 0

    async function loadLog() {
      try {
        const res = await api.fileText(path)
        if (cancelled) return
        setContent(String(res?.content || ''))
        setError('')
        setStatus('ready')
        setLastLoadedAt(new Date().toISOString())
      } catch (err) {
        if (cancelled) return
        setError(String(err?.message || err || 'Failed to load log'))
        setStatus('error')
      }
    }

    loadLog()
    if (shouldPoll) {
      timerId = window.setInterval(() => {
        loadLog()
      }, 2000)
    }

    return () => {
      cancelled = true
      if (timerId) window.clearInterval(timerId)
    }
  }, [path, shouldPoll])

  return (
    <div className="app log-viewer-page">
      <header>
        <h1>{runId ? `Run #${runId} Log` : 'Run Log Viewer'}</h1>
        <div className="header-right">
          <div className="muted">{actionType || 'automation run'}</div>
          <div className="muted">{shouldPoll ? 'Auto-refresh: ON' : 'Auto-refresh: OFF'}</div>
        </div>
      </header>
      <main>
        <div className="card">
          <div><b>Path:</b> {path || '-'}</div>
          <div><b>Status:</b> {status}</div>
          <div><b>Last loaded:</b> {lastLoadedAt ? formatGmt7(lastLoadedAt, 'en') : '-'}</div>
          {error ? <div className="error-text">{error}</div> : null}
          <pre className="log-viewer-pre">{content || (status === 'loading' ? 'Loading log...' : 'Log is empty.')}</pre>
        </div>
      </main>
    </div>
  )
}

export default function App() {
  const isLogViewer = useMemo(() => {
    if (typeof window === 'undefined') return false
    const params = new URLSearchParams(window.location.search || '')
    return params.get('view') === 'log'
  }, [])
  if (isLogViewer) {
    return <LogViewerPage />
  }

  const [active, setActive] = useState(() => readStoredState(ACTIVE_TAB_STATE_KEY, 'dashboard'))
  const [dashboard, setDashboard] = useState(null)
  const [appliedTrend, setAppliedTrend] = useState(null)
  const [countriesOverview, setCountriesOverview] = useState([])
  const [countries, setCountries] = useState([])
  const [countryGroups, setCountryGroups] = useState([])
  const [programmingLanguages, setProgrammingLanguages] = useState([])
  const [programmingLanguageGroups, setProgrammingLanguageGroups] = useState([])
  const [health, setHealth] = useState('')
  const [lang, setLang] = useState(localStorage.getItem('job_ops_lang') || 'en')
  const [jobsPreset, setJobsPreset] = useState(null)

  const t = i18n[lang] || i18n.en
  const tabs = [
    { key: 'dashboard', label: t.dashboard },
    { key: 'jobs', label: t.jobs },
    { key: 'applied_jobs', label: t.appliedJobsPage || t.appliedJobs || 'Applied Jobs' },
    { key: 'analytics', label: t.analytics },
    { key: 'learning', label: t.learningQuiz },
    { key: 'automation', label: t.automation },
  ]

  async function reloadAppData() {
    return api.health().then((h) => {
      setHealth(h.status || 'ok')
      return Promise.all([
        api.dashboard(),
        api.appliedJobsTrend().catch(() => null),
        api.countriesOverview().catch(() => ({ items: [] })),
        api.countries(),
        api.regionCountries(),
        api.programmingLanguages(),
        api.programmingLanguageGroups(),
      ]).then(([d, trend, overview, c, rc, pl, plg]) => {
        setDashboard(d)
        setAppliedTrend(trend)
        setCountriesOverview(overview.items || [])
        setCountries(c.items || [])
        setCountryGroups(rc.items || [])
        setProgrammingLanguages(pl.items || [])
        setProgrammingLanguageGroups(plg.items || [])
      })
    }).catch((e) => {
      setHealth(`offline: ${e.message}`)
      setDashboard(null)
      setAppliedTrend(null)
      setCountriesOverview([])
      setCountries([])
      setCountryGroups([])
      setProgrammingLanguages([])
      setProgrammingLanguageGroups([])
    })
  }

  useEffect(() => {
    if (appDidBootstrap) return
    appDidBootstrap = true
    reloadAppData()
  }, [])

  useEffect(() => {
    writeStoredState(ACTIVE_TAB_STATE_KEY, active)
  }, [active])

  function changeLang(value) {
    setLang(value)
    localStorage.setItem('job_ops_lang', value)
  }

  function openJobsWithPreset(preset) {
    setJobsPreset({ ...preset, limit: '50', offset: '0' })
    setActive(String(preset?.stage || '') === 'applied' ? 'applied_jobs' : 'jobs')
  }

  const content = useMemo(() => {
    if (active === 'dashboard') return <DashboardTab data={dashboard} trend={appliedTrend} countryOverview={countriesOverview} t={t} lang={lang} onOpenJobs={openJobsWithPreset} />
    if (active === 'jobs') return <JobsTab countries={countries} countryGroups={countryGroups} programmingLanguages={programmingLanguages} programmingLanguageGroups={programmingLanguageGroups} t={t} preset={jobsPreset} />
    if (active === 'applied_jobs') return <JobsTab countries={countries} countryGroups={countryGroups} programmingLanguages={programmingLanguages} programmingLanguageGroups={programmingLanguageGroups} t={t} preset={{ ...(jobsPreset || {}), stage: 'applied' }} tabTitle={t.appliedJobsPage || t.appliedJobs || 'Applied Jobs'} forceAppliedView />
    if (active === 'analytics') return <AnalyticsTab countries={countries} countryGroups={countryGroups} t={t} onOpenJobs={openJobsWithPreset} />
    if (active === 'learning') return <LearningQuizTab t={t} lang={lang} />
    return <AutomationTab t={t} lang={lang} onDataChanged={reloadAppData} />
  }, [active, dashboard, appliedTrend, countriesOverview, countries, countryGroups, programmingLanguages, programmingLanguageGroups, t, lang, jobsPreset])

  return (
    <div className="app">
      <header>
        <h1>{t.appTitle}</h1>
        <div className="header-right">
          <label className="muted">
            {t.language}:{' '}
            <select value={lang} onChange={(e) => changeLang(e.target.value)}>
              <option value="en">EN</option>
              <option value="vi">VI</option>
            </select>
          </label>
          <div className="muted">{t.backendHealth}: {health || 'loading...'}</div>
        </div>
      </header>
      <nav>
        {tabs.map((tab) => (
          <button key={tab.key} className={active === tab.key ? 'active' : ''} onClick={() => setActive(tab.key)}>
            {tab.label}
          </button>
        ))}
      </nav>
      <main>{content}</main>
    </div>
  )
}


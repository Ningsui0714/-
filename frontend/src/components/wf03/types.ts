import type { WF03FeedbackCode } from '../../services/api'

export interface WF03Selection {
  text: string
  targetType: 'step' | 'knowledge' | 'skill' | 'document'
  targetId?: string
  rect: { left: number; top: number; width: number; height: number }
}

export interface WF03Annotation {
  id: string
  selectedText: string
  targetType: WF03Selection['targetType']
  targetId?: string
  feedbackCode: WF03FeedbackCode
  severity: 'info' | 'warning' | 'error'
  message: string
  suggestedCorrection: string
  createdAt: string
}

/**
 * Enterprise Salesforce Apex Support Case Manager.
 * Demonstrates:
 *   - SOQL queries with limits
 *   - Bulk DML updates (governor limit compliance)
 *   - Custom Exception handling
 *   - @AuraEnabled methods for LWC components
 *   - Sharing rules
 */
public with sharing class CaseManager {

    public class CaseManagerException extends Exception {}

    /**
     * Create a new support case with priority validation.
     */
    @AuraEnabled
    public static Case createSupportCase(String subject, String description, String priority) {
        if (String.isBlank(subject)) {
            throw new CaseManagerException('Subject is mandatory');
        }

        String validPriority = 'Medium';
        if (priority != null && (priority == 'Low' || priority == 'Medium' || priority == 'High' || priority == 'Critical')) {
            validPriority = priority;
        }

        Case newCase = new Case(
            Subject = subject,
            Description = description,
            Priority = validPriority,
            Status = 'New'
        );

        insert newCase;
        return newCase;
    }

    /**
     * Escalate urgent cases in bulk to ensure governor limits compliance.
     * Takes a list of Case IDs and updates their status to 'Escalated'.
     */
    @AuraEnabled
    public static Integer escalatePriorityCases(List<Id> caseIds) {
        if (caseIds == null || caseIds.isEmpty()) {
            return 0;
        }

        List<Case> casesToEscalate = [
            SELECT Id, Status, Priority 
            FROM Case 
            WHERE Id IN :caseIds 
            AND Status != 'Closed'
        ];

        for (Case c : casesToEscalate) {
            c.Status = 'Escalated';
            c.Priority = 'High';
        }

        update casesToEscalate;
        return casesToEscalate.size();
    }

    /**
     * Auto-close stale cases resolved more than specified days ago.
     */
    public static Integer closeStaleResolvedCases(Integer daysThreshold) {
        if (daysThreshold == null || daysThreshold < 1) {
            throw new CaseManagerException('Days threshold must be at least 1');
        }

        Date cutoff = Date.today().addDays(-daysThreshold);

        List<Case> staleCases = [
            SELECT Id, Status 
            FROM Case 
            WHERE Status = 'Resolved' 
            AND ClosedDate < :cutoff 
            LIMIT 200
        ];

        for (Case c : staleCases) {
            c.Status = 'Closed';
        }

        if (!staleCases.isEmpty()) {
            update staleCases;
        }

        return staleCases.size();
    }
}

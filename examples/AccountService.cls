/**
 * Sample Apex class for testing the AI Test Case Generator.
 * Demonstrates common Salesforce patterns:
 *   - SOQL queries
 *   - DML operations
 *   - @AuraEnabled methods
 *   - Exception handling
 *   - Governor limit considerations
 */
public with sharing class AccountService {

    /**
     * Create a new Account record with validation.
     * @param name      Account name (required)
     * @param industry  Industry classification
     * @param revenue   Annual revenue
     * @return The newly created Account with Id populated
     */
    public static Account createAccount(String name, String industry, Decimal revenue) {
        if (String.isBlank(name)) {
            throw new AccountServiceException('Account name is required');
        }
        if (revenue != null && revenue < 0) {
            throw new AccountServiceException('Revenue cannot be negative');
        }

        Account acc = new Account(
            Name = name,
            Industry = industry,
            AnnualRevenue = revenue
        );
        insert acc;
        return acc;
    }

    /**
     * Retrieve accounts by industry with a revenue threshold.
     * @param industry       Industry to filter by
     * @param minRevenue     Minimum annual revenue
     * @return List of matching Account records
     */
    @AuraEnabled(cacheable=true)
    public static List<Account> getAccountsByIndustry(String industry, Decimal minRevenue) {
        if (String.isBlank(industry)) {
            throw new AuraHandledException('Industry parameter is required');
        }

        return [
            SELECT Id, Name, Industry, AnnualRevenue, CreatedDate
            FROM Account
            WHERE Industry = :industry
            AND AnnualRevenue >= :minRevenue
            ORDER BY AnnualRevenue DESC
            LIMIT 100
        ];
    }

    /**
     * Update the industry for a list of accounts.
     * Handles bulk operations for governor limit compliance.
     * @param accountIds    List of Account IDs to update
     * @param newIndustry   New industry value
     * @return Number of records updated
     */
    @AuraEnabled
    public static Integer updateAccountIndustry(List<Id> accountIds, String newIndustry) {
        if (accountIds == null || accountIds.isEmpty()) {
            return 0;
        }
        if (String.isBlank(newIndustry)) {
            throw new AuraHandledException('New industry value is required');
        }

        List<Account> accounts = [
            SELECT Id, Industry
            FROM Account
            WHERE Id IN :accountIds
        ];

        for (Account acc : accounts) {
            acc.Industry = newIndustry;
        }

        update accounts;
        return accounts.size();
    }

    /**
     * Calculate the total revenue for all accounts in a given industry.
     * @param industry  Industry to calculate total for
     * @return Total annual revenue
     */
    public static Decimal getTotalRevenueByIndustry(String industry) {
        AggregateResult[] results = [
            SELECT SUM(AnnualRevenue) totalRevenue
            FROM Account
            WHERE Industry = :industry
        ];

        Decimal total = (Decimal) results[0].get('totalRevenue');
        return total != null ? total : 0;
    }

    /**
     * Delete accounts with zero revenue that are older than the specified days.
     * @param daysOld  Number of days since creation
     * @return Number of records deleted
     */
    public static Integer cleanupStaleAccounts(Integer daysOld) {
        if (daysOld == null || daysOld < 0) {
            throw new AccountServiceException('Days must be a positive number');
        }

        Date cutoffDate = Date.today().addDays(-daysOld);

        List<Account> staleAccounts = [
            SELECT Id
            FROM Account
            WHERE AnnualRevenue = 0
            AND CreatedDate < :cutoffDate
            LIMIT 200
        ];

        if (!staleAccounts.isEmpty()) {
            delete staleAccounts;
        }

        return staleAccounts.size();
    }

    /**
     * Custom exception class for AccountService errors.
     */
    public class AccountServiceException extends Exception {}
}

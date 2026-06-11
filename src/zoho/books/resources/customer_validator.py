import re
import logging
from typing import Any, Dict, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor
from ..base import BaseResource

logger = logging.getLogger("zoho_books")

class CustomerValidator(BaseResource):
    """
    Helper resource under ZohoBooksAPI to validate customer contact data.
    """
    def __init__(self, client: Any):
        super().__init__(client, 'contacts')

    def check_proper_casing(self, text: str) -> List[str]:
        """
        Checks if the words in the text are in proper/title case.
        Allows numbers, acronyms, and standard prepositions/conjunctions.
        """
        if not text:
            return []
        # Replace common punctuations with space for splitting
        clean_text = re.sub(r'[^\w\s-]', ' ', text)
        words = clean_text.split()
        violations = []
        
        allowed_lower = {'and', 'or', 'of', 'in', 'at', 'to', 'near', 'opposite', 'with', 'by', 'for', 'the', 'a', 'an'}
        roman_numerals = {'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x'}
        
        for w in words:
            # Skip if contains numbers
            if re.search(r'\d', w):
                continue
            # Skip acronyms (2-4 uppercase characters)
            if len(w) >= 2 and len(w) <= 4 and w.isupper():
                continue
            # Skip allowed lowercase prepositions/conjunctions
            if w.lower() in allowed_lower and w.islower():
                continue
            # Skip roman numerals
            if w.lower() in roman_numerals and w.isupper():
                continue
                
            # Check proper case structure (uppercase first char, rest lowercase)
            is_proper = w[0].isupper() and (len(w) == 1 or w[1:].islower())
            if not is_proper:
                violations.append(w)
        return violations

    def check_punctuation_anomalies(self, text: str) -> List[str]:
        """
        Checks for double spaces, duplicate commas, missing spaces after commas,
        spaces before commas/periods, and trailing punctuation.
        """
        if not text:
            return []
        anomalies = []
        text_str = str(text).strip()
        
        if "  " in text_str:
            anomalies.append("Double space")
        if ",," in text_str:
            anomalies.append("Duplicate commas")
        if re.search(r'\s[,\.]', text_str):
            anomalies.append("Space before punctuation")
        if re.search(r',[^\s\d]', text_str):
            anomalies.append("Missing space after comma")
        if text_str.endswith(',') or text_str.endswith('.'):
            anomalies.append("Trailing punctuation")
            
        return anomalies

    def check_phone_isd(self, number: str) -> Optional[str]:
        """
        Validates phone/mobile number to ensure it starts with '+' and country code.
        """
        if not number:
            return None
        num_str = str(number).strip()
        if not num_str.startswith('+'):
            return f"Missing '+' prefix for ISD code (found: '{number}')"
        # Extract digits after the leading '+'
        digits = re.sub(r'\D', '', num_str[1:])
        if len(digits) < 7 or len(digits) > 15:
            return f"Invalid international format (found: '{number}')"
        return None

    def check_geographic_name(self, contact: Dict[str, Any]) -> Optional[str]:
        """
        Checks that contact_name or company_name contains their billing/shipping city
        or district/jurisdiction custom fields (case-insensitive).
        Supports synonym mapping for Tiruchirappalli and Trichy.
        """
        name = str(contact.get('contact_name', '')).lower().strip()
        company = str(contact.get('company_name', '')).lower().strip()
        
        geo_words = set()
        
        # 1. Check billing & shipping cities
        for addr_key in ['billing_address', 'shipping_address']:
            addr = contact.get(addr_key) or {}
            city = addr.get('city')
            if city:
                city_cleaned = city.lower().strip()
                geo_words.add(city_cleaned)
                if "tiruchirappalli" in city_cleaned or "trichy" in city_cleaned or "try" in city_cleaned:
                    geo_words.update(["tiruchirappalli", "trichy", "try"])
                if "namakkal" in city_cleaned or "nmk" in city_cleaned:
                    geo_words.update(["namakkal", "nmk"])
                if "perambalur" in city_cleaned or "pblr" in city_cleaned:
                    geo_words.update(["perambalur", "pblr"])
                    
        # 2. Check custom fields (District and Jurisdiction)
        for cf in contact.get('custom_fields', []):
            label = str(cf.get('label', '')).lower().strip()
            val = str(cf.get('value', '')).lower().strip()
            if label in ('district', 'jurisdiction') and val:
                geo_words.add(val)
                if "tiruchirappalli" in val or "trichy" in val or "try" in val:
                    geo_words.update(["tiruchirappalli", "trichy", "try"])
                if "namakkal" in val or "nmk" in val:
                    geo_words.update(["namakkal", "nmk"])
                if "perambalur" in val or "pblr" in val:
                    geo_words.update(["perambalur", "pblr"])
                    
        # Filter empty words
        geo_words = {w for w in geo_words if w}
        if not geo_words:
            return "No billing/shipping city or district/jurisdiction configured for geographic match verification"
            
        # Match check
        matched = False
        for word in geo_words:
            if word in name or word in company:
                matched = True
                break
                
        if not matched:
            expected_keywords = ", ".join(sorted(list(geo_words)))
            return f"Name does not contain any associated geographic keywords (expected one of: {expected_keywords})"
            
        return None

    def check_custom_fields(self, contact: Dict[str, Any]) -> List[str]:
        """
        Checks that Branch, District, Jurisdiction, and Transport custom fields are set.
        """
        required = {'branch', 'district', 'jurisdiction', 'transport'}
        found = set()
        
        for cf in contact.get('custom_fields', []):
            label = str(cf.get('label', '')).lower().strip()
            val = str(cf.get('value', '')).strip()
            if label in required and val:
                found.add(label)
                
        missing = required - found
        return [f"Missing custom field: {lbl.capitalize()}" for lbl in sorted(list(missing))]

    def validate_customer_data(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Lists all customer contacts and performs details analysis concurrently.
        """
        logger.info("Fetching all customer contacts...")
        # Get basic list
        contacts_list = self.client.contacts.list_all(params={"contact_type": "customer"})
        total_found = len(contacts_list)
        
        if limit is not None:
            contacts_list = contacts_list[:limit]
            
        logger.info(f"Processing details for {len(contacts_list)} / {total_found} contacts...")
        
        # Concurrently fetch detailed contact records
        def fetch_details(c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            c_id = c.get('contact_id')
            if not c_id:
                return None
            try:
                res = self.client.contacts.get(c_id)
                return res.get('contact')
            except Exception as e:
                logger.error(f"Failed to fetch details for contact {c_id}: {e}")
                return None

        with ThreadPoolExecutor(max_workers=15) as executor:
            detailed_contacts = list(executor.map(fetch_details, contacts_list))
            
        detailed_contacts = [dc for dc in detailed_contacts if dc is not None]
        
        report = []
        compliant_count = 0
        
        for contact in detailed_contacts:
            name = contact.get('contact_name', 'Unnamed Contact')
            c_id = contact.get('contact_id')
            issues = []
            
            # 1. Address validations
            for addr_key in ['billing_address', 'shipping_address']:
                addr = contact.get(addr_key) or {}
                # check proper casing of street/address line
                street = addr.get('address', '')
                casing_errors = self.check_proper_casing(street)
                if casing_errors:
                    issues.append({
                        "field": f"{addr_key}.address",
                        "error_type": "Casing Issue",
                        "value": street,
                        "details": f"Words not proper-cased: {', '.join(casing_errors)}"
                    })
                    
                # check punctuation anomalies in street/address line
                punc_errors = self.check_punctuation_anomalies(street)
                if punc_errors:
                    issues.append({
                        "field": f"{addr_key}.address",
                        "error_type": "Punctuation Issue",
                        "value": street,
                        "details": f"Anomalies: {', '.join(punc_errors)}"
                    })
                    
                # check proper casing of city
                city = addr.get('city', '')
                city_casing_errors = self.check_proper_casing(city)
                if city_casing_errors:
                    issues.append({
                        "field": f"{addr_key}.city",
                        "error_type": "Casing Issue",
                        "value": city,
                        "details": f"Words not proper-cased: {', '.join(city_casing_errors)}"
                    })
                    
                # check proper casing of state
                state = addr.get('state', '')
                state_casing_errors = self.check_proper_casing(state)
                if state_casing_errors:
                    issues.append({
                        "field": f"{addr_key}.state",
                        "error_type": "Casing Issue",
                        "value": state,
                        "details": f"Words not proper-cased: {', '.join(state_casing_errors)}"
                    })
            
            # 2. Phone number ISD validations
            for ph_key in ['phone', 'mobile']:
                val = contact.get(ph_key)
                phone_err = self.check_phone_isd(val)
                if phone_err:
                    issues.append({
                        "field": ph_key,
                        "error_type": "ISD Code Issue",
                        "value": val,
                        "details": phone_err
                    })
            
            # 3. Name geography checks
            geo_err = self.check_geographic_name(contact)
            if geo_err:
                issues.append({
                    "field": "contact_name",
                    "error_type": "Geography Match Issue",
                    "value": name,
                    "details": geo_err
                })
                
            # 4. Custom fields checks
            cf_errors = self.check_custom_fields(contact)
            for err in cf_errors:
                issues.append({
                    "field": "custom_fields",
                    "error_type": "Custom Field Issue",
                    "value": "N/A",
                    "details": err
                })
                
            if not issues:
                compliant_count += 1
            else:
                report.append({
                    "contact_id": c_id,
                    "contact_name": name,
                    "issues": issues
                })
                
        return {
            "total_contacts_in_books": total_found,
            "processed_count": len(detailed_contacts),
            "compliant_count": compliant_count,
            "non_compliant_count": len(report),
            "compliance_rate": round((compliant_count / len(detailed_contacts)) * 100, 2) if detailed_contacts else 0.0,
            "report": report
        }
